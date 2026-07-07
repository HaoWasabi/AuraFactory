"""Property tests for ContextService in-memory cache.

Validates: Requirements 4 (memory cache hit avoids DB call) and 5 (cache invalidation).
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.context_service import ContextService


def make_context_service(db_cached=None, discord_data=None):
    """Build a ContextService with mocked DB and MCP dependencies."""
    db = MagicMock()
    mcp = MagicMock()
    cs = ContextService(db, mcp)
    # Mock _get_cached to return db_cached (or None)
    cs._get_cached = AsyncMock(return_value=db_cached)
    # Mock _fetch_from_discord to return discord_data
    cs._fetch_from_discord = AsyncMock(
        return_value=discord_data
        or {"categories": "[]", "channels": "[]", "roles": "[]", "server_info": "{}"}
    )
    db.execute = AsyncMock(return_value="OK")
    return cs, db


# Feature: optimization, Property 4: Memory cache hit avoids DB call
# Validates: Requirements 4
@given(guild_id=st.integers(min_value=1, max_value=10**15))
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_memory_cache_hit_avoids_db_call(guild_id):
    """After cache warm, second call must not invoke _get_cached.

    **Validates: Requirements 4**
    """
    cached_data = {"categories": "[]", "channels": "[]", "roles": "[]", "server_info": "{}"}
    cs, db = make_context_service(db_cached=cached_data)

    # First call warms the memory cache (from DB cache)
    await cs.get_server_context(guild_id)
    cs._get_cached.reset_mock()

    # Second call within TTL must use memory cache, not DB
    result = await cs.get_server_context(guild_id)
    cs._get_cached.assert_not_called()
    assert result == cached_data


# Feature: optimization, Property 5: Cache invalidation clears memory cache
# Validates: Requirements 5
@given(guild_id=st.integers(min_value=1, max_value=10**15))
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_cache_invalidation_clears_memory_cache(guild_id):
    """After invalidate(), memory cache entry must be gone.

    **Validates: Requirements 5**
    """
    cached_data = {"categories": "[]", "channels": "[]", "roles": "[]", "server_info": "{}"}
    cs, db = make_context_service(db_cached=cached_data)

    # Warm memory cache
    await cs.get_server_context(guild_id)
    assert guild_id in cs._memory_cache

    # Invalidate — should remove the memory cache entry
    await cs.invalidate(guild_id)
    assert guild_id not in cs._memory_cache


@pytest.mark.asyncio
async def test_force_refresh_bypasses_memory_cache():
    """force_refresh=True skips both memory cache and DB cache."""
    guild_id = 42
    cached_data = {"categories": "[]", "channels": "[]", "roles": "[]", "server_info": "{}"}
    cs, db = make_context_service(db_cached=cached_data)

    # Warm cache
    await cs.get_server_context(guild_id)
    cs._get_cached.reset_mock()
    cs._fetch_from_discord.reset_mock()

    # Force refresh — should call Discord directly, not memory or DB cache
    await cs.get_server_context(guild_id, force_refresh=True)
    cs._get_cached.assert_not_called()
    cs._fetch_from_discord.assert_called_once()


@pytest.mark.asyncio
async def test_memory_cache_populated_after_db_cache_hit():
    """When DB cache is hit, result is stored in memory cache for next call."""
    guild_id = 99
    cached_data = {"categories": "[1]", "channels": "[2]", "roles": "[3]", "server_info": "{}"}
    cs, db = make_context_service(db_cached=cached_data)

    # Initially empty memory cache
    assert guild_id not in cs._memory_cache

    await cs.get_server_context(guild_id)

    # Memory cache should now be populated
    assert guild_id in cs._memory_cache
    assert cs._memory_cache[guild_id][0] == cached_data
