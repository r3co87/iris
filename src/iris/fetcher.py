"""Playwright-based page fetcher with retry and error classification."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from iris.config import Settings
from iris.logging import get_logger
from iris.schemas import FetchError, FetchErrorType, WaitStrategy
from iris.wait_strategy import SmartWaiter

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright, Response

logger = get_logger(__name__)

# HTTP status codes that are retryable
_RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

# Content types we handle
_HTML_TYPES = {"text/html", "application/xhtml+xml"}
_PDF_TYPES = {"application/pdf"}
_JSON_TYPES = {"application/json"}
_TEXT_TYPES = {"text/plain"}
_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}


def classify_error(exc: Exception, url: str = "") -> FetchError:
    """Classify an exception into a structured FetchError.

    Args:
        exc: The exception that occurred.
        url: The URL being fetched (for context).

    Returns:
        A FetchError with appropriate type and retryable flag.
    """
    error_str = str(exc).lower()
    exc_name = type(exc).__name__

    if isinstance(exc, TimeoutError) or "timeout" in error_str:
        return FetchError(
            type=FetchErrorType.TIMEOUT,
            message=f"{exc_name}: {exc}",
            retryable=True,
        )

    dns_keywords = ("dns", "name resolution", "getaddrinfo")
    if any(kw in error_str for kw in dns_keywords):
        return FetchError(
            type=FetchErrorType.DNS_ERROR,
            message=f"{exc_name}: {exc}",
            retryable=True,
        )

    if "ssl" in error_str or "certificate" in error_str:
        return FetchError(
            type=FetchErrorType.SSL_ERROR,
            message=f"{exc_name}: {exc}",
            retryable=False,
        )

    if (
        "connection" in error_str
        or "reset" in error_str
        or "refused" in error_str
        or "broken pipe" in error_str
        or isinstance(exc, ConnectionError)
    ):
        return FetchError(
            type=FetchErrorType.CONNECTION_ERROR,
            message=f"{exc_name}: {exc}",
            retryable=True,
        )

    # Default: browser error
    return FetchError(
        type=FetchErrorType.BROWSER_ERROR,
        message=f"{exc_name}: {exc}",
        retryable=False,
    )


def classify_http_error(status_code: int) -> FetchError:
    """Classify an HTTP status code error.

    Args:
        status_code: The HTTP status code.

    Returns:
        A FetchError with appropriate type and retryable flag.
    """
    retryable = status_code in _RETRYABLE_STATUS_CODES
    if status_code == 429:
        return FetchError(
            type=FetchErrorType.RATE_LIMITED,
            message=f"HTTP {status_code}: Too Many Requests",
            retryable=True,
            http_status=status_code,
        )
    return FetchError(
        type=FetchErrorType.HTTP_ERROR,
        message=f"HTTP {status_code}",
        retryable=retryable,
        http_status=status_code,
    )


def _get_content_type(content_type_header: str | None) -> str:
    """Extract the base content type without parameters."""
    if not content_type_header:
        return "text/html"
    return content_type_header.split(";")[0].strip().lower()


def _is_pdf_url(url: str) -> bool:
    """Check if URL looks like a PDF."""
    return urlparse(url).path.lower().endswith(".pdf")


class FetchResult:
    """Raw result from a page fetch before content extraction."""

    def __init__(
        self,
        url: str,
        status_code: int,
        html: str,
        screenshot_bytes: bytes | None = None,
        error: FetchError | None = None,
        fetch_time_ms: int = 0,
        content_type: str = "text/html",
        raw_bytes: bytes | None = None,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.html = html
        self.screenshot_bytes = screenshot_bytes
        self.error = error
        self.fetch_time_ms = fetch_time_ms
        self.content_type = content_type
        self.raw_bytes = raw_bytes


class PageFetcher:
    """Playwright-based async page fetcher with retry logic."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_PAGES)
        self._waiter = SmartWaiter()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if browser is connected."""
        return self._connected and self._browser is not None

    @property
    def active_pages(self) -> int:
        """Number of currently active pages (approx via semaphore)."""
        return self.settings.MAX_CONCURRENT_PAGES - self._semaphore._value

    async def start(self) -> None:
        """Launch browser instance."""
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()

        browser_type = getattr(self._playwright, self.settings.BROWSER_TYPE)
        self._browser = await browser_type.launch(headless=self.settings.HEADLESS)
        self._context = await self._browser.new_context(
            user_agent=self.settings.USER_AGENT,
        )
        self._connected = True
        logger.info(
            "Browser started: type=%s headless=%s",
            self.settings.BROWSER_TYPE,
            self.settings.HEADLESS,
        )

    async def close(self) -> None:
        """Close browser and playwright."""
        if self._context:
            await self._context.close()
            self._context = None
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        self._connected = False
        logger.info("Browser closed")

    async def fetch(
        self,
        url: str,
        *,
        wait_for_selector: str | None = None,
        wait_after_load_ms: int | None = None,
        wait_strategy: WaitStrategy = WaitStrategy.LOAD,
        timeout_ms: int | None = None,
        take_screenshot: bool = False,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """Fetch a page with JS rendering and automatic retries.

        Args:
            url: URL to fetch.
            wait_for_selector: CSS selector to wait for after page load.
            wait_after_load_ms: Time to wait after load event (ms).
            wait_strategy: Strategy for waiting on dynamic content.
            timeout_ms: Page navigation timeout (ms).
            take_screenshot: Whether to capture a screenshot.
            headers: Custom HTTP headers.

        Returns:
            FetchResult with content and optional screenshot.
        """
        if not self._context:
            return FetchResult(
                url=url,
                status_code=0,
                html="",
                error=FetchError(
                    type=FetchErrorType.BROWSER_ERROR,
                    message="Browser not started",
                    retryable=False,
                ),
            )

        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return FetchResult(
                url=url,
                status_code=0,
                html="",
                error=FetchError(
                    type=FetchErrorType.INVALID_URL,
                    message=f"Invalid URL: {url}",
                    retryable=False,
                ),
            )

        # Auto-select SELECTOR strategy when selector is provided
        effective_strategy = wait_strategy
        if wait_for_selector and wait_strategy == WaitStrategy.LOAD:
            effective_strategy = WaitStrategy.SELECTOR

        timeout = timeout_ms or self.settings.PAGE_TIMEOUT_MS
        wait_after = wait_after_load_ms or self.settings.WAIT_AFTER_LOAD_MS
        max_retries = self.settings.MAX_RETRIES
        start_time = time.monotonic()

        async with self._semaphore:
            last_result: FetchResult | None = None

            for attempt in range(max_retries + 1):
                if attempt > 0:
                    backoff = 2 ** (attempt - 1)
                    logger.info(
                        "Retry %d/%d for %s (backoff %ds)",
                        attempt,
                        max_retries,
                        url,
                        backoff,
                    )
                    await asyncio.sleep(backoff)

                result = await self._fetch_once(
                    url=url,
                    wait_for_selector=wait_for_selector,
                    wait_after_load_ms=wait_after,
                    wait_strategy=effective_strategy,
                    timeout_ms=timeout,
                    take_screenshot=take_screenshot,
                    headers=headers,
                    start_time=start_time,
                )
                last_result = result

                if result.error is None:
                    return result

                # Check if error is retryable
                if not result.error.retryable:
                    return result

                # For HTTP 429, respect Retry-After
                if (
                    result.error.type == FetchErrorType.RATE_LIMITED
                    and attempt < max_retries
                ):
                    # We already have backoff, but 429 might need more
                    pass

                if attempt >= max_retries:
                    return result

            # Should not reach here, but just in case
            assert last_result is not None
            return last_result

    async def _fetch_once(
        self,
        url: str,
        *,
        wait_for_selector: str | None,
        wait_after_load_ms: int,
        wait_strategy: WaitStrategy,
        timeout_ms: int,
        take_screenshot: bool,
        headers: dict[str, str] | None,
        start_time: float,
    ) -> FetchResult:
        """Execute a single fetch attempt."""
        assert self._context is not None

        page: Page | None = None
        try:
            page = await self._context.new_page()

            if headers:
                await page.set_extra_http_headers(headers)

            # Navigate
            response: Response | None = await page.goto(
                url, timeout=timeout_ms, wait_until="load"
            )
            status_code = response.status if response else 0

            # Detect content type
            content_type_header = (
                response.headers.get("content-type") if response else None
            )
            content_type = _get_content_type(content_type_header)

            # Check for HTTP errors
            if status_code >= 400:
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                error = classify_http_error(status_code)
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html="",
                    error=error,
                    fetch_time_ms=elapsed_ms,
                    content_type=content_type,
                )

            # Handle PDF content type (or .pdf URL)
            if content_type in _PDF_TYPES or (
                _is_pdf_url(url) and content_type == "application/octet-stream"
            ):
                raw_bytes = await response.body() if response else b""
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html="",
                    fetch_time_ms=elapsed_ms,
                    content_type="application/pdf",
                    raw_bytes=raw_bytes,
                )

            # Handle JSON
            if content_type in _JSON_TYPES:
                import json

                raw_bytes = await response.body() if response else b""
                try:
                    parsed_json = json.loads(raw_bytes)
                    pretty = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                except Exception:
                    pretty = raw_bytes.decode("utf-8", errors="replace")
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html=pretty,
                    fetch_time_ms=elapsed_ms,
                    content_type="application/json",
                )

            # Handle plain text
            if content_type in _TEXT_TYPES:
                text = await page.content()
                # Strip HTML wrapper that Playwright adds
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(text, "lxml")
                body = soup.find("body")
                plain_text = body.get_text() if body else text
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html=plain_text,
                    fetch_time_ms=elapsed_ms,
                    content_type="text/plain",
                )

            # Handle images — metadata only
            if content_type.startswith("image/"):
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html="",
                    fetch_time_ms=elapsed_ms,
                    content_type=content_type,
                )

            # Unsupported content types
            if content_type not in _HTML_TYPES and content_type != "text/html":
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                return FetchResult(
                    url=url,
                    status_code=status_code,
                    html="",
                    error=FetchError(
                        type=FetchErrorType.UNSUPPORTED_CONTENT_TYPE,
                        message=f"Unsupported content type: {content_type}",
                        retryable=False,
                    ),
                    fetch_time_ms=elapsed_ms,
                    content_type=content_type,
                )

            # HTML content — apply wait strategy
            if wait_strategy != WaitStrategy.LOAD:
                await self._waiter.wait(
                    page,
                    wait_strategy,
                    selector=wait_for_selector,
                    timeout_ms=timeout_ms,
                    wait_ms=wait_after_load_ms,
                )

            # Additional wait for JS rendering
            if wait_after_load_ms > 0 and wait_strategy != WaitStrategy.TIMEOUT:
                await page.wait_for_timeout(wait_after_load_ms)

            html = await page.content()

            screenshot_bytes: bytes | None = None
            if take_screenshot:
                screenshot_bytes = await page.screenshot(type="png", full_page=True)

            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return FetchResult(
                url=url,
                status_code=status_code,
                html=html,
                screenshot_bytes=screenshot_bytes,
                fetch_time_ms=elapsed_ms,
                content_type=content_type,
            )

        except Exception as e:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            error = classify_error(e, url)
            logger.error("Fetch error: url=%s error=%s", url, error.message)
            return FetchResult(
                url=url,
                status_code=0,
                html="",
                error=error,
                fetch_time_ms=elapsed_ms,
            )
        finally:
            if page:
                await page.close()

    async def screenshot(self, url: str) -> bytes:
        """Take a full-page screenshot.

        Args:
            url: URL to screenshot.

        Returns:
            PNG screenshot as bytes.

        Raises:
            RuntimeError: If screenshot fails.
        """
        result = await self.fetch(url, take_screenshot=True)
        if result.error:
            msg = f"Screenshot failed: {result.error.message}"
            raise RuntimeError(msg)
        if result.screenshot_bytes is None:
            msg = "Screenshot returned no data"
            raise RuntimeError(msg)
        return result.screenshot_bytes

    @staticmethod
    def screenshot_to_base64(screenshot_bytes: bytes) -> str:
        """Convert screenshot bytes to base64 string."""
        return base64.b64encode(screenshot_bytes).decode("utf-8")
