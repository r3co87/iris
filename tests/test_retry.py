"""Tests for retry logic in PageFetcher."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris.config import Settings
from iris.fetcher import PageFetcher
from iris.schemas import FetchErrorType


@pytest.fixture
def retry_settings() -> Settings:
    return Settings(
        TESTING_MODE=True,
        MAX_CONCURRENT_PAGES=2,
        MIN_DELAY_BETWEEN_REQUESTS_MS=0,
        RESPECT_ROBOTS_TXT=False,
        PAGE_TIMEOUT_MS=5000,
        WAIT_AFTER_LOAD_MS=0,
        MAX_RETRIES=2,
    )


@pytest.fixture
def mock_page() -> MagicMock:
    page = MagicMock()
    resp = MagicMock(status=200, headers={"content-type": "text/html"})
    page.goto = AsyncMock(return_value=resp)
    page.content = AsyncMock(return_value="<html><body>OK</body></html>")
    page.close = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"png")
    page.set_extra_http_headers = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    return page


@pytest.fixture
def mock_context(mock_page: MagicMock) -> MagicMock:
    context = MagicMock()
    context.new_page = AsyncMock(return_value=mock_page)
    context.close = AsyncMock()
    return context


@pytest.fixture
def fetcher(retry_settings: Settings, mock_context: MagicMock) -> PageFetcher:
    f = PageFetcher(retry_settings)
    f._context = mock_context
    f._connected = True
    return f


class TestRetryLogic:
    """Tests for automatic retry on transient errors."""

    @pytest.mark.asyncio
    async def test_no_retry_on_success(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should not retry when fetch succeeds."""
        result = await fetcher.fetch("https://example.com")
        assert result.error is None
        assert result.status_code == 200
        # Only one page created
        assert fetcher._context.new_page.call_count == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_retry_on_timeout(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should retry on timeout errors."""
        call_count = 0

        async def goto_with_timeout(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise TimeoutError("Navigation timeout")
            return MagicMock(status=200, headers={"content-type": "text/html"})

        mock_page.goto = AsyncMock(side_effect=goto_with_timeout)

        with patch("iris.fetcher.asyncio.sleep", new_callable=AsyncMock):
            result = await fetcher.fetch("https://example.com")

        assert result.error is None
        assert call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_retry_on_connection_error(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should retry on connection errors."""
        call_count = 0

        async def goto_with_error(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Connection reset")
            return MagicMock(status=200, headers={"content-type": "text/html"})

        mock_page.goto = AsyncMock(side_effect=goto_with_error)

        with patch("iris.fetcher.asyncio.sleep", new_callable=AsyncMock):
            result = await fetcher.fetch("https://example.com")

        assert result.error is None
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_http_429(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should retry on HTTP 429 Too Many Requests."""
        call_count = 0

        async def goto_429(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(status=429, headers={"content-type": "text/html"})
            return MagicMock(status=200, headers={"content-type": "text/html"})

        mock_page.goto = AsyncMock(side_effect=goto_429)

        with patch("iris.fetcher.asyncio.sleep", new_callable=AsyncMock):
            result = await fetcher.fetch("https://example.com")

        assert result.error is None
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_retry_on_http_502(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should retry on HTTP 502."""
        call_count = 0

        async def goto_502(*args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(status=502, headers={"content-type": "text/html"})
            return MagicMock(status=200, headers={"content-type": "text/html"})

        mock_page.goto = AsyncMock(side_effect=goto_502)

        with patch("iris.fetcher.asyncio.sleep", new_callable=AsyncMock):
            result = await fetcher.fetch("https://example.com")

        assert result.error is None

    @pytest.mark.asyncio
    async def test_no_retry_on_404(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should NOT retry on HTTP 404."""
        mock_page.goto = AsyncMock(
            return_value=MagicMock(status=404, headers={"content-type": "text/html"})
        )

        result = await fetcher.fetch("https://example.com/missing")
        assert result.error is not None
        assert result.error.type == FetchErrorType.HTTP_ERROR
        assert result.error.retryable is False
        # Only one attempt
        assert fetcher._context.new_page.call_count == 1  # type: ignore[union-attr]

    @pytest.mark.asyncio
    async def test_no_retry_on_403(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should NOT retry on HTTP 403."""
        mock_page.goto = AsyncMock(
            return_value=MagicMock(status=403, headers={"content-type": "text/html"})
        )

        result = await fetcher.fetch("https://example.com/forbidden")
        assert result.error is not None
        assert result.error.retryable is False

    @pytest.mark.asyncio
    async def test_no_retry_on_invalid_url(self, fetcher: PageFetcher) -> None:
        """Should NOT retry on invalid URL."""
        result = await fetcher.fetch("not-a-url")
        assert result.error is not None
        assert result.error.type == FetchErrorType.INVALID_URL
        assert result.error.retryable is False

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(
        self, fetcher: PageFetcher, mock_page: MagicMock
    ) -> None:
        """Should give up after max retries."""
        mock_page.goto = AsyncMock(side_effect=TimeoutError("Always timeout"))

        with patch("iris.fetcher.asyncio.sleep", new_callable=AsyncMock):
            result = await fetcher.fetch("https://example.com")

        assert result.error is not None
        assert result.error.type == FetchErrorType.TIMEOUT
        # 1 initial + 2 retries = 3
        assert fetcher._context.new_page.call_count == 3  # type: ignore[union-attr]
