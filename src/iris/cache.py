"""Redis cache layer for Iris with graceful degradation."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import redis.asyncio as redis

from iris.config import Settings
from iris.logging import get_logger
from iris.schemas import FetchResponse

logger = get_logger(__name__)


def make_cache_key(url: str, **params: Any) -> str:
    """Generate a cache key from URL and request parameters.

    Args:
        url: The fetched URL.
        **params: Additional request parameters that affect the response.

    Returns:
        SHA256 hex digest as cache key.
    """
    filtered = {k: v for k, v in sorted(params.items()) if v is not None}
    key_data = {"url": url, **filtered}
    raw = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


class CacheLayer:
    """Redis-based cache with graceful degradation."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: redis.Redis | None = None  # type: ignore[type-arg]
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if Redis is reachable."""
        return self._connected

    async def connect(self) -> None:
        """Initialize Redis connection."""
        if not self.settings.CACHE_ENABLED:
            logger.info("Cache disabled by configuration")
            return

        try:
            self._client = redis.from_url(
                self.settings.REDIS_URL,
                decode_responses=True,
            )
            # Test connection
            await self._client.ping()
            self._connected = True
            logger.info("Cache connected: url=%s", self.settings.REDIS_URL)
        except Exception as e:
            logger.warning("Cache connection failed: %s", e)
            self._client = None
            self._connected = False

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            self._connected = False
            logger.info("Cache closed")

    async def get(self, key: str) -> FetchResponse | None:
        """Get a cached response.

        Args:
            key: Cache key (SHA256 hash).

        Returns:
            Cached FetchResponse or None if not found/error.
        """
        if not self._client or not self.settings.CACHE_ENABLED:
            return None

        try:
            data = await self._client.get(f"iris:fetch:{key}")
            if data is None:
                return None
            return FetchResponse.model_validate_json(data)
        except Exception as e:
            logger.warning("Cache get failed: key=%s error=%s", key, e)
            return None

    async def set(
        self, key: str, response: FetchResponse, ttl: int | None = None
    ) -> None:
        """Cache a response.

        Args:
            key: Cache key (SHA256 hash).
            response: FetchResponse to cache.
            ttl: TTL in seconds (defaults to CACHE_TTL_SECONDS).
        """
        if not self._client or not self.settings.CACHE_ENABLED:
            return

        try:
            cache_ttl = ttl or self.settings.CACHE_TTL_SECONDS
            data = response.model_dump_json()
            await self._client.setex(f"iris:fetch:{key}", cache_ttl, data)
            logger.debug("Cache set: key=%s ttl=%ds", key, cache_ttl)
        except Exception as e:
            logger.warning("Cache set failed: key=%s error=%s", key, e)

    async def invalidate(self, key: str) -> bool:
        """Invalidate a cached entry.

        Args:
            key: Cache key (SHA256 hash).

        Returns:
            True if key was deleted, False otherwise.
        """
        if not self._client or not self.settings.CACHE_ENABLED:
            return False

        try:
            result = await self._client.delete(f"iris:fetch:{key}")
            return bool(result)
        except Exception as e:
            logger.warning("Cache invalidate failed: key=%s error=%s", key, e)
            return False

    async def stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache stats or empty dict on error.
        """
        if not self._client or not self.settings.CACHE_ENABLED:
            return {"enabled": False}

        try:
            info: dict[str, Any] = await self._client.info("memory")  # type: ignore[assignment]
            keys = await self._client.dbsize()
            return {
                "enabled": True,
                "connected": self._connected,
                "keys": keys,
                "used_memory": info.get("used_memory_human", "unknown"),
            }
        except Exception as e:
            logger.warning("Cache stats failed: %s", e)
            return {"enabled": True, "connected": False, "error": str(e)}
