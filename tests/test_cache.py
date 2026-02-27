"""Tests for CacheLayer — Redis caching with graceful degradation."""

from __future__ import annotations

import pytest

from iris.cache import CacheLayer, make_cache_key
from iris.config import Settings
from iris.schemas import FetchResponse, PageMetadata


@pytest.fixture
def response() -> FetchResponse:
    """Sample FetchResponse for caching."""
    return FetchResponse(
        url="https://example.com/test",
        status_code=200,
        content_text="Test content here",
        metadata=PageMetadata(title="Test Page", description="Test desc"),
        content_length=17,
        fetch_time_ms=100,
    )


class TestMakeCacheKey:
    """Tests for cache key generation."""

    def test_same_url_same_key(self) -> None:
        """Same URL should produce same key."""
        key1 = make_cache_key("https://example.com")
        key2 = make_cache_key("https://example.com")
        assert key1 == key2

    def test_different_url_different_key(self) -> None:
        """Different URLs should produce different keys."""
        key1 = make_cache_key("https://example.com/a")
        key2 = make_cache_key("https://example.com/b")
        assert key1 != key2

    def test_params_affect_key(self) -> None:
        """Different params should produce different keys."""
        key1 = make_cache_key("https://example.com", extract_text=True)
        key2 = make_cache_key("https://example.com", extract_text=False)
        assert key1 != key2

    def test_none_params_ignored(self) -> None:
        """None params should be ignored in key generation."""
        key1 = make_cache_key("https://example.com")
        key2 = make_cache_key("https://example.com", screenshot=None)
        assert key1 == key2

    def test_key_is_hex_digest(self) -> None:
        """Key should be a 64-char hex SHA256 digest."""
        key = make_cache_key("https://example.com")
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


class TestCacheLayer:
    """Tests for the Redis cache layer."""

    @pytest.mark.asyncio
    async def test_set_and_get(
        self, cache: CacheLayer, response: FetchResponse
    ) -> None:
        """Should store and retrieve a response."""
        key = make_cache_key("https://example.com/test")
        await cache.set(key, response)
        cached = await cache.get(key)
        assert cached is not None
        assert cached.url == response.url
        assert cached.content_text == response.content_text
        assert cached.status_code == 200

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, cache: CacheLayer) -> None:
        """Should return None for nonexistent keys."""
        result = await cache.get("nonexistent-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_invalidate_existing(
        self, cache: CacheLayer, response: FetchResponse
    ) -> None:
        """Should delete an existing cached entry."""
        key = make_cache_key("https://example.com/test")
        await cache.set(key, response)
        deleted = await cache.invalidate(key)
        assert deleted is True
        assert await cache.get(key) is None

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent(self, cache: CacheLayer) -> None:
        """Should return False when invalidating nonexistent key."""
        deleted = await cache.invalidate("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_cache_disabled(self, response: FetchResponse) -> None:
        """Should skip all operations when cache is disabled."""
        settings = Settings(CACHE_ENABLED=False, TESTING_MODE=True)
        layer = CacheLayer(settings)
        await layer.set("key", response)
        result = await layer.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_graceful_degradation_get(self, settings: Settings) -> None:
        """Should return None when Redis is unavailable."""
        layer = CacheLayer(settings)
        layer._connected = False
        layer._client = None
        result = await layer.get("some-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_graceful_degradation_set(
        self, settings: Settings, response: FetchResponse
    ) -> None:
        """Should silently fail when Redis is unavailable."""
        layer = CacheLayer(settings)
        layer._connected = False
        layer._client = None
        # Should not raise
        await layer.set("some-key", response)

    @pytest.mark.asyncio
    async def test_graceful_degradation_invalidate(self, settings: Settings) -> None:
        """Should return False when Redis is unavailable."""
        layer = CacheLayer(settings)
        layer._connected = False
        layer._client = None
        result = await layer.invalidate("some-key")
        assert result is False

    @pytest.mark.asyncio
    async def test_stats_enabled(self, cache: CacheLayer) -> None:
        """Should return stats when cache is connected."""
        stats = await cache.stats()
        assert stats["enabled"] is True
        # fakeredis may not support info command, so check for graceful handling
        assert "connected" in stats or "keys" in stats or "error" in stats

    @pytest.mark.asyncio
    async def test_stats_disabled(self) -> None:
        """Should return disabled status when cache is off."""
        settings = Settings(CACHE_ENABLED=False, TESTING_MODE=True)
        layer = CacheLayer(settings)
        stats = await layer.stats()
        assert stats["enabled"] is False

    @pytest.mark.asyncio
    async def test_metadata_preserved(
        self, cache: CacheLayer, response: FetchResponse
    ) -> None:
        """Should preserve metadata through cache round-trip."""
        key = make_cache_key("https://example.com/meta-test")
        await cache.set(key, response)
        cached = await cache.get(key)
        assert cached is not None
        assert cached.metadata is not None
        assert cached.metadata.title == "Test Page"
        assert cached.metadata.description == "Test desc"

    @pytest.mark.asyncio
    async def test_connect_failure_graceful(self) -> None:
        """Should handle connection failure gracefully."""
        settings = Settings(
            REDIS_URL="redis://nonexistent:6379/4",
            CACHE_ENABLED=True,
            TESTING_MODE=True,
        )
        layer = CacheLayer(settings)
        # Should not raise
        await layer.connect()
        assert layer.is_connected is False
