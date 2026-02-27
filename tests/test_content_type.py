"""Tests for content type detection and handling."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from iris.config import Settings
from iris.fetcher import PageFetcher, _get_content_type, _is_pdf_url
from iris.schemas import FetchErrorType


@pytest.fixture
def ct_settings() -> Settings:
    return Settings(
        TESTING_MODE=True,
        MAX_CONCURRENT_PAGES=2,
        MIN_DELAY_BETWEEN_REQUESTS_MS=0,
        RESPECT_ROBOTS_TXT=False,
        PAGE_TIMEOUT_MS=5000,
        WAIT_AFTER_LOAD_MS=0,
        MAX_RETRIES=0,
    )


def _make_page(
    status: int = 200,
    content_type: str = "text/html",
    body: bytes = b"<html><body>Hello</body></html>",
    html: str = "<html><body>Hello</body></html>",
) -> MagicMock:
    """Create a mock page with configurable content type."""
    response = MagicMock()
    response.status = status
    response.headers = {"content-type": content_type}
    response.body = AsyncMock(return_value=body)

    page = MagicMock()
    page.goto = AsyncMock(return_value=response)
    page.content = AsyncMock(return_value=html)
    page.close = AsyncMock()
    page.set_extra_http_headers = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"png")
    return page


class TestContentTypeHelpers:
    """Tests for content type utility functions."""

    def test_get_content_type_basic(self) -> None:
        assert _get_content_type("text/html") == "text/html"

    def test_get_content_type_with_charset(self) -> None:
        assert _get_content_type("text/html; charset=utf-8") == "text/html"

    def test_get_content_type_none(self) -> None:
        assert _get_content_type(None) == "text/html"

    def test_get_content_type_json(self) -> None:
        ct = _get_content_type("application/json; charset=utf-8")
        assert ct == "application/json"

    def test_is_pdf_url_true(self) -> None:
        assert _is_pdf_url("https://example.com/doc.pdf") is True

    def test_is_pdf_url_false(self) -> None:
        assert _is_pdf_url("https://example.com/page.html") is False

    def test_is_pdf_url_case_insensitive(self) -> None:
        assert _is_pdf_url("https://example.com/doc.PDF") is True


class TestContentTypeHandling:
    """Tests for handling different content types in the fetcher."""

    @pytest.fixture
    def fetcher(self, ct_settings: Settings) -> PageFetcher:
        f = PageFetcher(ct_settings)
        f._connected = True
        return f

    @pytest.mark.asyncio
    async def test_html_content(self, fetcher: PageFetcher) -> None:
        """Should handle text/html normally."""
        page = _make_page(content_type="text/html")
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        fetcher._context = context

        result = await fetcher.fetch("https://example.com")
        assert result.content_type == "text/html"
        assert "Hello" in result.html

    @pytest.mark.asyncio
    async def test_json_content(self, fetcher: PageFetcher) -> None:
        """Should handle application/json by pretty-printing."""
        data = {"key": "value", "num": 42}
        page = _make_page(
            content_type="application/json",
            body=json.dumps(data).encode(),
        )
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        fetcher._context = context

        result = await fetcher.fetch("https://api.example.com/data")
        assert result.content_type == "application/json"
        assert '"key"' in result.html
        assert '"value"' in result.html

    @pytest.mark.asyncio
    async def test_pdf_content(self, fetcher: PageFetcher) -> None:
        """Should handle application/pdf with raw bytes."""
        page = _make_page(
            content_type="application/pdf",
            body=b"%PDF-1.4 fake pdf bytes",
        )
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        fetcher._context = context

        result = await fetcher.fetch("https://example.com/doc.pdf")
        assert result.content_type == "application/pdf"
        assert result.raw_bytes is not None

    @pytest.mark.asyncio
    async def test_plain_text_content(self, fetcher: PageFetcher) -> None:
        """Should handle text/plain."""
        page = _make_page(
            content_type="text/plain",
            html="<html><body><pre>Plain text content</pre></body></html>",
        )
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        fetcher._context = context

        result = await fetcher.fetch("https://example.com/readme.txt")
        assert result.content_type == "text/plain"

    @pytest.mark.asyncio
    async def test_image_content(self, fetcher: PageFetcher) -> None:
        """Should handle image/* with metadata only."""
        page = _make_page(content_type="image/png", body=b"png-data")
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        fetcher._context = context

        result = await fetcher.fetch("https://example.com/photo.png")
        assert result.content_type == "image/png"
        assert result.html == ""

    @pytest.mark.asyncio
    async def test_unsupported_content_type(self, fetcher: PageFetcher) -> None:
        """Should return error for unsupported content types."""
        page = _make_page(content_type="application/octet-stream")
        context = MagicMock()
        context.new_page = AsyncMock(return_value=page)
        fetcher._context = context

        result = await fetcher.fetch("https://example.com/file.bin")
        assert result.error is not None
        assert result.error.type == FetchErrorType.UNSUPPORTED_CONTENT_TYPE
