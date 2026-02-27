"""Tests for SmartWaiter — wait strategies for dynamic content."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from iris.schemas import WaitStrategy
from iris.wait_strategy import SmartWaiter


@pytest.fixture
def waiter() -> SmartWaiter:
    return SmartWaiter()


@pytest.fixture
def mock_page() -> MagicMock:
    page = MagicMock()
    page.wait_for_load_state = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    return page


class TestSmartWaiter:
    """Tests for different wait strategies."""

    @pytest.mark.asyncio
    async def test_load_strategy(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """LOAD strategy should be a no-op (handled by goto)."""
        await waiter.wait(mock_page, WaitStrategy.LOAD)
        mock_page.wait_for_load_state.assert_not_called()
        mock_page.wait_for_selector.assert_not_called()

    @pytest.mark.asyncio
    async def test_networkidle_strategy(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """NETWORKIDLE strategy should wait for network idle."""
        await waiter.wait(mock_page, WaitStrategy.NETWORKIDLE, timeout_ms=5000)
        mock_page.wait_for_load_state.assert_called_once_with(
            "networkidle", timeout=5000
        )

    @pytest.mark.asyncio
    async def test_domcontentloaded_strategy(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """DOMCONTENTLOADED strategy should wait for DOMContentLoaded."""
        await waiter.wait(mock_page, WaitStrategy.DOMCONTENTLOADED, timeout_ms=5000)
        mock_page.wait_for_load_state.assert_called_once_with(
            "domcontentloaded", timeout=5000
        )

    @pytest.mark.asyncio
    async def test_selector_strategy(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """SELECTOR strategy should wait for a specific CSS selector."""
        await waiter.wait(
            mock_page, WaitStrategy.SELECTOR, selector=".content", timeout_ms=5000
        )
        mock_page.wait_for_selector.assert_called_once_with(".content", timeout=5000)

    @pytest.mark.asyncio
    async def test_selector_strategy_no_selector(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """SELECTOR strategy without selector should not crash."""
        await waiter.wait(mock_page, WaitStrategy.SELECTOR)
        mock_page.wait_for_selector.assert_not_called()

    @pytest.mark.asyncio
    async def test_timeout_strategy(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """TIMEOUT strategy should wait for specified milliseconds."""
        await waiter.wait(mock_page, WaitStrategy.TIMEOUT, wait_ms=2000)
        mock_page.wait_for_timeout.assert_called_once_with(2000)

    @pytest.mark.asyncio
    async def test_timeout_strategy_zero(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """TIMEOUT strategy with 0ms should not wait."""
        await waiter.wait(mock_page, WaitStrategy.TIMEOUT, wait_ms=0)
        mock_page.wait_for_timeout.assert_not_called()

    @pytest.mark.asyncio
    async def test_networkidle_timeout_graceful(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """Should handle networkidle timeout gracefully."""
        mock_page.wait_for_load_state = AsyncMock(side_effect=TimeoutError("Timed out"))
        # Should not raise
        await waiter.wait(mock_page, WaitStrategy.NETWORKIDLE, timeout_ms=1000)

    @pytest.mark.asyncio
    async def test_selector_timeout_graceful(
        self, waiter: SmartWaiter, mock_page: MagicMock
    ) -> None:
        """Should handle selector timeout gracefully."""
        mock_page.wait_for_selector = AsyncMock(side_effect=TimeoutError("Timed out"))
        # Should not raise
        await waiter.wait(
            mock_page, WaitStrategy.SELECTOR, selector=".missing", timeout_ms=1000
        )
