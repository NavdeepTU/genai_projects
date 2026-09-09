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


# Short on purpose: this bounds how long a revoked-but-not-actively-cleared
# session (or MCP user) can still be treated as valid, for any path that
# somehow skips invalidate_identity. Active invalidation on logout is the
# real defense; this is just the backstop.
IDENTITY_CACHE_TTL_SECONDS = 60


def _identity_cache_key(token: str) -> str:
    """Build the Redis key one caller's cached identity is stored under.

    Keyed by the exact value user_id_middleware already looks up on every
    request — a session cookie's token, or MCP's X-User-Id header — so a
    cache hit replaces the database lookup entirely instead of needing a
    second index into it.
    """
    return f"identity:{token}"


async def get_cached_identity(token: str) -> dict | None:
    """Return this token's cached {user_id, tenant_id}, or None on a miss or an outage."""
    try:
        raw = await circuit_breaker.call(lambda: client.get(_identity_cache_key(token)))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.exception("Redis unavailable or returned invalid data, falling back")
        return None


async def cache_identity(token: str, user_id: str, tenant_id: str) -> None:
    """Best-effort write — a caching failure here must never fail the request itself."""
    try:
        await circuit_breaker.call(
            lambda: client.set(
                _identity_cache_key(token),
                json.dumps({"user_id": user_id, "tenant_id": tenant_id}),
                ex=IDENTITY_CACHE_TTL_SECONDS,
            )
        )
    except Exception:
        logger.exception("Redis unavailable, skipping identity cache write")


async def invalidate_identity(token: str) -> None:
    """Clear a cached identity immediately — called on logout, so a revoked
    session can't still be treated as valid for the rest of its TTL window."""
    try:
        await circuit_breaker.call(lambda: client.delete(_identity_cache_key(token)))
    except Exception:
        logger.exception("Redis unavailable, skipping identity cache invalidation")
