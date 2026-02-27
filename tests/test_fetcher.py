"""Tests for PageFetcher — Playwright-based fetching (mocked)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from iris.config import Settings
from iris.fetcher import PageFetcher
from iris.schemas import FetchErrorType


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
        MAX_RETRIES=0,  # No retries for basic fetcher tests
    )


@pytest.fixture
def mock_page() -> MagicMock:
    """Create a mock Playwright page."""
    page = MagicMock()
    page.goto = AsyncMock(
        return_value=MagicMock(status=200, headers={"content-type": "text/html"})
    )
    page.content = AsyncMock(return_value="<html><body>Hello</body></html>")
    page.close = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"fake-png-data")
    page.set_extra_http_headers = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.wait_for_load_state = AsyncMock()
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
        assert result.error.type == FetchErrorType.TIMEOUT
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
        assert result.error is not None
        assert result.error.type == FetchErrorType.BROWSER_ERROR
        assert "Browser not started" in result.error.message

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should limit concurrent pages via semaphore."""
        event = asyncio.Event()

        async def slow_goto(*args, **kwargs):  # type: ignore[no-untyped-def]
            await event.wait()
            return MagicMock(status=200, headers={"content-type": "text/html"})

        mock_page.goto = AsyncMock(side_effect=slow_goto)
        fetcher._context.new_page = AsyncMock(return_value=mock_page)  # type: ignore[union-attr]

        tasks = [
            asyncio.create_task(fetcher.fetch(f"https://example.com/{i}"))
            for i in range(3)
        ]

        await asyncio.sleep(0.05)
        assert fetcher.active_pages == 2

        event.set()
        results = await asyncio.gather(*tasks)
        assert len(results) == 3

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
        fetcher._browser = MagicMock()
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

    @pytest.mark.asyncio
    async def test_invalid_url(self, fetcher: PageFetcher) -> None:
        """Should return INVALID_URL error for malformed URLs."""
        result = await fetcher.fetch("not-a-url")
        assert result.error is not None
        assert result.error.type == FetchErrorType.INVALID_URL
        assert result.error.retryable is False

    @pytest.mark.asyncio
    async def test_content_type_tracked(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should track the content type of the response."""
        result = await fetcher.fetch("https://example.com")
        assert result.content_type == "text/html"
