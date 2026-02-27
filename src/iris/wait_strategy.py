"""Smart wait strategies for dynamic content loading."""

from __future__ import annotations

from typing import TYPE_CHECKING

from iris.logging import get_logger
from iris.schemas import WaitStrategy

if TYPE_CHECKING:
    from playwright.async_api import Page

logger = get_logger(__name__)


class SmartWaiter:
    """Wait for dynamic content using configurable strategies."""

    async def wait(
        self,
        page: Page,
        strategy: WaitStrategy,
        *,
        selector: str | None = None,
        timeout_ms: int = 30000,
        wait_ms: int = 0,
    ) -> None:
        """Apply a wait strategy to a page.

        Args:
            page: Playwright page instance.
            strategy: The wait strategy to use.
            selector: CSS selector (required for SELECTOR strategy).
            timeout_ms: Maximum wait time in milliseconds.
            wait_ms: Duration in ms for TIMEOUT strategy.
        """
        if strategy == WaitStrategy.LOAD:
            # load event is already handled by page.goto wait_until="load"
            pass
        elif strategy == WaitStrategy.NETWORKIDLE:
            try:
                await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except Exception:
                logger.warning("networkidle wait timed out")
        elif strategy == WaitStrategy.DOMCONTENTLOADED:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            except Exception:
                logger.warning("domcontentloaded wait timed out")
        elif strategy == WaitStrategy.SELECTOR:
            if selector:
                try:
                    await page.wait_for_selector(selector, timeout=timeout_ms)
                except Exception:
                    logger.warning("Selector wait timed out: selector=%s", selector)
            else:
                logger.warning("SELECTOR strategy used without a selector")
        elif strategy == WaitStrategy.TIMEOUT and wait_ms > 0:
            await page.wait_for_timeout(wait_ms)
