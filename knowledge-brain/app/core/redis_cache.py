import json
import logging

import redis.asyncio as redis

from app.core.circuit_breaker import CircuitBreaker
from app.core.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
client = redis.from_url(settings.redis_url, decode_responses=True)
circuit_breaker = CircuitBreaker(name="redis_cache")

# Long enough that resuming a conversation the next day still gets a
# fast condensing lookup; short enough not to accumulate forever.
RECENT_TURNS_TTL_SECONDS = 60 * 60 * 24


def _cache_key(conversation_id: str) -> str:
    """Build the Redis key one conversation's cached recent turns are stored under."""
    return f"conversation_turns:{conversation_id}"


async def get_recent_turns(conversation_id: str) -> list[dict] | None:
    """Return this conversation's cached recent turns, or None on a miss or an outage.

    Deliberately catches broadly, not just CircuitOpenError: this is a
    pure performance cache with a real fallback right behind it, and
    neither Redis being unreachable on its very first call (before the
    breaker has even opened) nor a corrupted/unexpected cached value
    (json.loads failing) may ever surface as a crash here — the exact
    gap named honestly in ADR-040 for a different circuit breaker,
    applied here so it isn't repeated.
    """
    try:
        raw = await circuit_breaker.call(lambda: client.get(_cache_key(conversation_id)))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.exception("Redis unavailable or returned invalid data, falling back")
        return None


async def cache_recent_turns(conversation_id: str, turns: list[dict]) -> None:
    """Best-effort write — a caching failure here must never fail the request itself."""
    try:
        await circuit_breaker.call(
            lambda: client.set(
                _cache_key(conversation_id), json.dumps(turns), ex=RECENT_TURNS_TTL_SECONDS
            )
        )
    except Exception:
        logger.exception("Redis unavailable, skipping recent-turns cache write")
