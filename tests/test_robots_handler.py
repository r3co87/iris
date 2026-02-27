"""Tests for RobotsHandler — robots.txt parsing, caching, graceful degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest

from iris.robots_handler import RobotsHandler


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def handler(fake_redis: fakeredis.aioredis.FakeRedis) -> RobotsHandler:
    return RobotsHandler(
        user_agent="Cortex-Iris/1.0",
        redis_client=fake_redis,
        cache_ttl=3600,
        respect_robots=True,
    )


@pytest.fixture
def handler_no_redis() -> RobotsHandler:
    return RobotsHandler(
        user_agent="Cortex-Iris/1.0",
        redis_client=None,
        cache_ttl=3600,
        respect_robots=True,
    )


@pytest.fixture
def handler_disabled() -> RobotsHandler:
    return RobotsHandler(
        user_agent="Cortex-Iris/1.0",
        redis_client=None,
        respect_robots=False,
    )


ROBOTS_DISALLOW = """User-agent: *
Disallow: /private/
Disallow: /admin/
"""

ROBOTS_ALLOW_ALL = """User-agent: *
Disallow:
"""

ROBOTS_SPECIFIC_BOT = """User-agent: Cortex-Iris
Disallow: /

User-agent: *
Disallow: /secret/
"""


class TestRobotsHandler:
    """Tests for robots.txt handling."""

    @pytest.mark.asyncio
    async def test_respect_disabled(self, handler_disabled: RobotsHandler) -> None:
        """Should allow all URLs when respect_robots is False."""
        result = await handler_disabled.can_fetch("https://example.com/private/page")
        assert result is True

    @pytest.mark.asyncio
    async def test_disallow_path(self, handler: RobotsHandler) -> None:
        """Should block disallowed paths."""
        with patch("iris.robots_handler.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = ROBOTS_DISALLOW
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handler.can_fetch("https://example.com/private/page")
            assert result is False

    @pytest.mark.asyncio
    async def test_allow_path(self, handler: RobotsHandler) -> None:
        """Should allow non-disallowed paths."""
        with patch("iris.robots_handler.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = ROBOTS_DISALLOW
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handler.can_fetch("https://example.com/public/page")
            assert result is True

    @pytest.mark.asyncio
    async def test_memory_cache_hit(self, handler: RobotsHandler) -> None:
        """Should use memory cache for repeated checks."""
        with patch("iris.robots_handler.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = ROBOTS_DISALLOW
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            # First call fetches
            await handler.can_fetch("https://example.com/page")
            # Second call should use memory cache
            await handler.can_fetch("https://example.com/other")
            # Only one HTTP call (for the same origin)
            assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_robots_not_found(self, handler: RobotsHandler) -> None:
        """Should allow all when robots.txt returns 404."""
        with patch("iris.robots_handler.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 404
            mock_resp.text = ""
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handler.can_fetch("https://example.com/anything")
            assert result is True

    @pytest.mark.asyncio
    async def test_robots_fetch_error(self, handler: RobotsHandler) -> None:
        """Should allow all when robots.txt fetch fails."""
        with patch("iris.robots_handler.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=ConnectionError("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handler.can_fetch("https://example.com/anything")
            assert result is True

    @pytest.mark.asyncio
    async def test_redis_cache_write(
        self, handler: RobotsHandler, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        """Should cache robots.txt content in Redis."""
        with patch("iris.robots_handler.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = ROBOTS_ALLOW_ALL
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            await handler.can_fetch("https://cached.com/page")
            cached = await fake_redis.get("iris:robots:https://cached.com")
            assert cached is not None

    @pytest.mark.asyncio
    async def test_no_redis_works(self, handler_no_redis: RobotsHandler) -> None:
        """Should work without Redis (memory-only caching)."""
        with patch("iris.robots_handler.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = ROBOTS_ALLOW_ALL
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            result = await handler_no_redis.can_fetch("https://example.com/page")
            assert result is True
