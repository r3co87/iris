"""Playwright-based page fetcher with concurrency control and politeness."""

from __future__ import annotations

import asyncio
import base64
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from iris.config import Settings
from iris.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserContext, Page, Playwright

logger = get_logger(__name__)


class RobotsChecker:
    """Simple robots.txt checker with caching."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[bool, float]] = {}
        self._cache_ttl = 3600.0  # 1 hour

    async def is_allowed(self, url: str, user_agent: str, *, page: Page) -> bool:
        """Check if URL is allowed by robots.txt."""
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        cache_key = f"{domain}:{parsed.path}"

        # Check cache
        if cache_key in self._cache:
            allowed, cached_at = self._cache[cache_key]
            if time.monotonic() - cached_at < self._cache_ttl:
                return allowed

        try:
            robots_url = f"{domain}/robots.txt"
            response = await page.goto(robots_url, timeout=5000)
            if response is None or response.status != 200:
                self._cache[cache_key] = (True, time.monotonic())
                return True

            content = await page.content()
            allowed = self._parse_robots(content, parsed.path, user_agent)
            self._cache[cache_key] = (allowed, time.monotonic())
            return allowed
        except Exception:
            # If we can't check robots.txt, allow the request
            self._cache[cache_key] = (True, time.monotonic())
            return True

    @staticmethod
    def _parse_robots(content: str, path: str, user_agent: str) -> bool:
        """Parse robots.txt content and check if path is allowed."""
        lines = content.strip().split("\n")
        current_agent_matches = False
        disallowed_paths: list[str] = []

        for line in lines:
            line = line.strip()
            if line.startswith("#") or not line:
                continue

            if ":" not in line:
                continue

            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()

            if key == "user-agent":
                agent_match = value.lower() in user_agent.lower()
                current_agent_matches = value == "*" or agent_match
            elif key == "disallow" and current_agent_matches and value:
                disallowed_paths.append(value)

        return all(not path.startswith(d) for d in disallowed_paths)


class FetchResult:
    """Raw result from a page fetch before content extraction."""

    def __init__(
        self,
        url: str,
        status_code: int,
        html: str,
        screenshot_bytes: bytes | None = None,
        error: str | None = None,
        fetch_time_ms: int = 0,
    ) -> None:
        self.url = url
        self.status_code = status_code
        self.html = html
        self.screenshot_bytes = screenshot_bytes
        self.error = error
        self.fetch_time_ms = fetch_time_ms


class PageFetcher:
    """Playwright-based async page fetcher with concurrency and rate limiting."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_PAGES)
        self._domain_last_request: dict[str, float] = {}
        self._domain_locks: dict[str, asyncio.Lock] = {}
        self._robots_checker = RobotsChecker()
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

    def _get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        parsed = urlparse(url)
        return parsed.netloc

    def _get_domain_lock(self, domain: str) -> asyncio.Lock:
        """Get or create a lock for a domain."""
        if domain not in self._domain_locks:
            self._domain_locks[domain] = asyncio.Lock()
        return self._domain_locks[domain]

    async def _enforce_rate_limit(self, domain: str) -> None:
        """Enforce minimum delay between requests to the same domain."""
        lock = self._get_domain_lock(domain)
        async with lock:
            now = time.monotonic()
            last_request = self._domain_last_request.get(domain, 0.0)
            min_delay = self.settings.MIN_DELAY_BETWEEN_REQUESTS_MS / 1000.0
            elapsed = now - last_request

            if elapsed < min_delay:
                wait_time = min_delay - elapsed
                logger.info("Rate limiting: domain=%s wait=%.2fs", domain, wait_time)
                await asyncio.sleep(wait_time)

            self._domain_last_request[domain] = time.monotonic()

    async def fetch(
        self,
        url: str,
        *,
        wait_for_selector: str | None = None,
        wait_after_load_ms: int | None = None,
        timeout_ms: int | None = None,
        take_screenshot: bool = False,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """Fetch a page with JS rendering.

        Args:
            url: URL to fetch.
            wait_for_selector: CSS selector to wait for after page load.
            wait_after_load_ms: Time to wait after load event (ms).
            timeout_ms: Page navigation timeout (ms).
            take_screenshot: Whether to capture a screenshot.
            headers: Custom HTTP headers.

        Returns:
            FetchResult with HTML content and optional screenshot.
        """
        if not self._context:
            return FetchResult(
                url=url, status_code=0, html="", error="Browser not started"
            )

        domain = self._get_domain(url)
        timeout = timeout_ms or self.settings.PAGE_TIMEOUT_MS
        wait_after = wait_after_load_ms or self.settings.WAIT_AFTER_LOAD_MS
        start_time = time.monotonic()

        async with self._semaphore:
            # Rate limiting
            await self._enforce_rate_limit(domain)

            page: Page | None = None
            try:
                page = await self._context.new_page()

                # Set custom headers
                if headers:
                    await page.set_extra_http_headers(headers)

                # Check robots.txt
                if self.settings.RESPECT_ROBOTS_TXT:
                    allowed = await self._robots_checker.is_allowed(
                        url, self.settings.USER_AGENT, page=page
                    )
                    if not allowed:
                        elapsed_ms = int((time.monotonic() - start_time) * 1000)
                        return FetchResult(
                            url=url,
                            status_code=403,
                            html="",
                            error="Blocked by robots.txt",
                            fetch_time_ms=elapsed_ms,
                        )

                # Navigate
                response = await page.goto(url, timeout=timeout, wait_until="load")
                status_code = response.status if response else 0

                # Wait for dynamic content
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(wait_for_selector, timeout=timeout)
                    except Exception:
                        logger.warning(
                            "Selector wait timeout: url=%s selector=%s",
                            url,
                            wait_for_selector,
                        )

                # Additional wait for JS rendering
                if wait_after > 0:
                    await page.wait_for_timeout(wait_after)

                # Get content
                html = await page.content()

                # Screenshot
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
                )

            except Exception as e:
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                error_msg = f"{type(e).__name__}: {e}"
                logger.error("Fetch error: url=%s error=%s", url, error_msg)
                return FetchResult(
                    url=url,
                    status_code=0,
                    html="",
                    error=error_msg,
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
            msg = f"Screenshot failed: {result.error}"
            raise RuntimeError(msg)
        if result.screenshot_bytes is None:
            msg = "Screenshot returned no data"
            raise RuntimeError(msg)
        return result.screenshot_bytes

    @staticmethod
    def screenshot_to_base64(screenshot_bytes: bytes) -> str:
        """Convert screenshot bytes to base64 string."""
        return base64.b64encode(screenshot_bytes).decode("utf-8")
