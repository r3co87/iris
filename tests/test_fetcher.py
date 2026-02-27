"""Tests for PageFetcher — Playwright-based fetching (mocked)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from iris.config import Settings
from iris.fetcher import PageFetcher, RobotsChecker


@pytest.fixture
def fetcher_settings() -> Settings:
    """Settings for fetcher tests."""
    return Settings(
        TESTING_MODE=True,
        MAX_CONCURRENT_PAGES=2,
        MIN_DELAY_BETWEEN_REQUESTS_MS=100,
        RESPECT_ROBOTS_TXT=False,
        PAGE_TIMEOUT_MS=5000,
        WAIT_AFTER_LOAD_MS=0,
    )


@pytest.fixture
def mock_page() -> MagicMock:
    """Create a mock Playwright page."""
    page = MagicMock()
    page.goto = AsyncMock(return_value=MagicMock(status=200))
    page.content = AsyncMock(return_value="<html><body>Hello</body></html>")
    page.close = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"fake-png-data")
    page.set_extra_http_headers = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    return page


@pytest.fixture
def mock_context(mock_page: MagicMock) -> MagicMock:
    """Create a mock browser context."""
    context = MagicMock()
    context.new_page = AsyncMock(return_value=mock_page)
    context.close = AsyncMock()
    return context


@pytest.fixture
def fetcher(fetcher_settings: Settings, mock_context: MagicMock) -> PageFetcher:
    """Create a fetcher with mocked browser context."""
    f = PageFetcher(fetcher_settings)
    f._context = mock_context
    f._connected = True
    return f


class TestPageFetcher:
    """Tests for the page fetcher."""

    @pytest.mark.asyncio
    async def test_fetch_basic(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should fetch a page and return HTML."""
        result = await fetcher.fetch("https://example.com")
        assert result.status_code == 200
        assert "Hello" in result.html
        assert result.error is None
        mock_page.goto.assert_called_once()
        mock_page.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_with_screenshot(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should take screenshot when requested."""
        result = await fetcher.fetch("https://example.com", take_screenshot=True)
        assert result.screenshot_bytes == b"fake-png-data"
        mock_page.screenshot.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_without_screenshot(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should not take screenshot by default."""
        result = await fetcher.fetch("https://example.com")
        assert result.screenshot_bytes is None
        mock_page.screenshot.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_with_selector_wait(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should wait for selector when provided."""
        await fetcher.fetch("https://example.com", wait_for_selector=".content")
        mock_page.wait_for_selector.assert_called_once_with(".content", timeout=5000)

    @pytest.mark.asyncio
    async def test_fetch_with_custom_headers(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should set custom headers."""
        headers = {"Authorization": "Bearer token123"}
        await fetcher.fetch("https://example.com", headers=headers)
        mock_page.set_extra_http_headers.assert_called_once_with(headers)

    @pytest.mark.asyncio
    async def test_fetch_timeout_error(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should handle timeout errors gracefully."""
        mock_page.goto = AsyncMock(side_effect=TimeoutError("Navigation timeout"))
        result = await fetcher.fetch("https://slow.example.com")
        assert result.error is not None
        assert "TimeoutError" in result.error
        assert result.status_code == 0

    @pytest.mark.asyncio
    async def test_fetch_network_error(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should handle network errors gracefully."""
        mock_page.goto = AsyncMock(side_effect=ConnectionError("DNS failed"))
        result = await fetcher.fetch("https://nonexistent.example.com")
        assert result.error is not None
        assert result.status_code == 0

    @pytest.mark.asyncio
    async def test_fetch_not_started(self, fetcher_settings: Settings) -> None:
        """Should return error if browser not started."""
        f = PageFetcher(fetcher_settings)
        result = await f.fetch("https://example.com")
        assert result.error == "Browser not started"

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should limit concurrent pages via semaphore."""
        # Create a slow fetch
        event = asyncio.Event()

        async def slow_goto(*args, **kwargs):  # type: ignore[no-untyped-def]
            await event.wait()
            return MagicMock(status=200)

        mock_page.goto = AsyncMock(side_effect=slow_goto)
        fetcher._context.new_page = AsyncMock(return_value=mock_page)  # type: ignore[union-attr]

        # Start MAX_CONCURRENT_PAGES + 1 tasks
        tasks = [
            asyncio.create_task(fetcher.fetch(f"https://example.com/{i}"))
            for i in range(3)
        ]

        # Let them start
        await asyncio.sleep(0.05)

        # With semaphore of 2, the third should be blocked
        assert fetcher.active_pages == 2

        # Release all
        event.set()
        results = await asyncio.gather(*tasks)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_rate_limiting(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should enforce delay between requests to the same domain."""
        import time

        start = time.monotonic()
        await fetcher.fetch("https://example.com/page1")
        await fetcher.fetch("https://example.com/page2")
        elapsed = time.monotonic() - start

        # With 100ms min delay, two requests should take at least 100ms
        assert elapsed >= 0.09  # Allow small tolerance

    @pytest.mark.asyncio
    async def test_rate_limiting_different_domains(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should not rate-limit requests to different domains."""
        import time

        start = time.monotonic()
        await fetcher.fetch("https://example1.com/page")
        await fetcher.fetch("https://example2.com/page")
        elapsed = time.monotonic() - start

        # Different domains should not be delayed
        assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_fetch_time_tracked(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should track fetch time in milliseconds."""
        result = await fetcher.fetch("https://example.com")
        assert result.fetch_time_ms >= 0

    @pytest.mark.asyncio
    async def test_page_closed_on_error(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should close page even when an error occurs."""
        mock_page.goto = AsyncMock(side_effect=RuntimeError("Crash"))
        await fetcher.fetch("https://example.com")
        mock_page.close.assert_called_once()

    def test_is_connected(self, fetcher: PageFetcher) -> None:
        """Should report connection status when browser is present."""
        fetcher._browser = MagicMock()  # Simulate real browser
        assert fetcher.is_connected is True

    def test_is_not_connected(self, fetcher_settings: Settings) -> None:
        """Should report disconnected when not started."""
        f = PageFetcher(fetcher_settings)
        assert f.is_connected is False

    def test_active_pages(self, fetcher: PageFetcher) -> None:
        """Should report 0 active pages when idle."""
        assert fetcher.active_pages == 0

    def test_screenshot_to_base64(self) -> None:
        """Should convert bytes to base64 string."""
        data = b"test-png-data"
        b64 = PageFetcher.screenshot_to_base64(data)
        assert isinstance(b64, str)
        import base64

        assert base64.b64decode(b64) == data


class TestRobotsChecker:
    """Tests for robots.txt checking."""

    def test_parse_robots_disallow(self) -> None:
        """Should detect disallowed paths."""
        robots = """User-agent: *
Disallow: /private/
Disallow: /admin/"""
        assert RobotsChecker._parse_robots(robots, "/private/page", "TestBot") is False
        assert RobotsChecker._parse_robots(robots, "/public/page", "TestBot") is True

    def test_parse_robots_allow_all(self) -> None:
        """Should allow all when no Disallow rules."""
        robots = """User-agent: *
Disallow:"""
        assert RobotsChecker._parse_robots(robots, "/anything", "TestBot") is True

    def test_parse_robots_empty(self) -> None:
        """Should allow all for empty robots.txt."""
        assert RobotsChecker._parse_robots("", "/anything", "TestBot") is True

    def test_parse_robots_specific_agent(self) -> None:
        """Should match specific user agent rules."""
        robots = """User-agent: BadBot
Disallow: /

User-agent: *
Disallow: /secret/"""
        # Our bot matches * but also BadBot if our name contains it
        assert RobotsChecker._parse_robots(robots, "/page", "GoodBot") is True
        assert RobotsChecker._parse_robots(robots, "/secret/data", "GoodBot") is False
