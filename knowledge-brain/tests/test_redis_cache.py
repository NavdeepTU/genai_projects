import json
from unittest.mock import AsyncMock, patch

from app.core.redis_cache import (
    cache_identity,
    cache_recent_turns,
    get_cached_identity,
    get_recent_turns,
    invalidate_identity,
)


async def test_get_recent_turns_returns_the_cached_list_on_a_hit():
    cached = [{"question": "How many vacation days?", "answer": "20 days."}]
    mock_client = AsyncMock()
    mock_client.get.return_value = json.dumps(cached)

    with patch("app.core.redis_cache.client", mock_client):
        result = await get_recent_turns("conv-1")

    assert result == cached
    mock_client.get.assert_awaited_once_with("conversation_turns:conv-1")


async def test_get_recent_turns_returns_none_on_a_genuine_cache_miss():
    mock_client = AsyncMock()
    mock_client.get.return_value = None

    with patch("app.core.redis_cache.client", mock_client):
        result = await get_recent_turns("conv-1")

    assert result is None


async def test_get_recent_turns_fails_open_when_redis_is_unreachable():
    """A raw connection error on the very first call — before the breaker has even
    opened — must still come back as None, not raise. This is the exact gap named
    in ADR-040 for a different circuit breaker; this cache is built not to repeat it.
    """
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("Redis is not running")

    with patch("app.core.redis_cache.client", mock_client):
        result = await get_recent_turns("conv-1")

    assert result is None


async def test_cache_recent_turns_writes_with_the_configured_ttl():
    mock_client = AsyncMock()
    turns = [{"question": "How many vacation days?", "answer": "20 days."}]

    with patch("app.core.redis_cache.client", mock_client):
        await cache_recent_turns("conv-1", turns)

    mock_client.set.assert_awaited_once_with(
        "conversation_turns:conv-1", json.dumps(turns), ex=60 * 60 * 24
    )


async def test_cache_recent_turns_never_raises_when_redis_is_unreachable():
    """A caching failure must never fail the actual request it's attached to."""
    mock_client = AsyncMock()
    mock_client.set.side_effect = ConnectionError("Redis is not running")

    with patch("app.core.redis_cache.client", mock_client):
        await cache_recent_turns("conv-1", [{"question": "q", "answer": "a"}])
    # No exception means the fail-open contract held.


async def test_get_recent_turns_fails_open_on_a_corrupted_cached_value():
    """A hit that isn't valid JSON must degrade the same way an outage does, not raise."""
    mock_client = AsyncMock()
    mock_client.get.return_value = "not valid json{{"

    with patch("app.core.redis_cache.client", mock_client):
        result = await get_recent_turns("conv-1")

    assert result is None


async def test_get_cached_identity_returns_the_cached_value_on_a_hit():
    mock_client = AsyncMock()
    mock_client.get.return_value = json.dumps({"user_id": "u1", "tenant_id": "t1"})

    with patch("app.core.redis_cache.client", mock_client):
        result = await get_cached_identity("token-1")

    assert result == {"user_id": "u1", "tenant_id": "t1"}
    mock_client.get.assert_awaited_once_with("identity:token-1")


async def test_get_cached_identity_returns_none_on_a_genuine_cache_miss():
    mock_client = AsyncMock()
    mock_client.get.return_value = None

    with patch("app.core.redis_cache.client", mock_client):
        result = await get_cached_identity("token-1")

    assert result is None


async def test_get_cached_identity_fails_open_when_redis_is_unreachable():
    mock_client = AsyncMock()
    mock_client.get.side_effect = ConnectionError("Redis is not running")

    with patch("app.core.redis_cache.client", mock_client):
        result = await get_cached_identity("token-1")

    assert result is None


async def test_get_cached_identity_fails_open_on_a_corrupted_cached_value():
    mock_client = AsyncMock()
    mock_client.get.return_value = "not valid json{{"

    with patch("app.core.redis_cache.client", mock_client):
        result = await get_cached_identity("token-1")

    assert result is None


async def test_cache_identity_writes_with_the_configured_ttl():
    mock_client = AsyncMock()

    with patch("app.core.redis_cache.client", mock_client):
        await cache_identity("token-1", "u1", "t1")

    mock_client.set.assert_awaited_once_with(
        "identity:token-1", json.dumps({"user_id": "u1", "tenant_id": "t1"}), ex=60
    )


async def test_cache_identity_never_raises_when_redis_is_unreachable():
    mock_client = AsyncMock()
    mock_client.set.side_effect = ConnectionError("Redis is not running")

    with patch("app.core.redis_cache.client", mock_client):
        await cache_identity("token-1", "u1", "t1")
    # No exception means the fail-open contract held.


async def test_invalidate_identity_deletes_the_cache_key():
    mock_client = AsyncMock()

    with patch("app.core.redis_cache.client", mock_client):
        await invalidate_identity("token-1")

    mock_client.delete.assert_awaited_once_with("identity:token-1")


async def test_invalidate_identity_never_raises_when_redis_is_unreachable():
    mock_client = AsyncMock()
    mock_client.delete.side_effect = ConnectionError("Redis is not running")

    with patch("app.core.redis_cache.client", mock_client):
        await invalidate_identity("token-1")
    # No exception means the fail-open contract held.
