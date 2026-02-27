"""Tests for API routes — health, fetch, batch, cache endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from iris.cache import CacheLayer
from iris.config import Settings
from iris.extractor import ContentExtractor
from iris.fetcher import FetchResult, PageFetcher
from iris.routes.fetch import router as fetch_router
from iris.routes.health import router as health_router
from iris.schemas import FetchError, FetchErrorType, FetchResponse


@pytest.fixture
def test_settings() -> Settings:
    """Test settings."""
    return Settings(TESTING_MODE=True, MAX_CONTENT_LENGTH=10000)


@pytest.fixture
def mock_fetch_result() -> FetchResult:
    """Standard successful fetch result."""
    return FetchResult(
        url="https://example.com",
        status_code=200,
        html="""<html><head><title>Test</title>
<meta name="description" content="Test page"></head>
<body><p>Test content paragraph.</p>
<a href="https://example.com/link">Link</a></body></html>""",
        fetch_time_ms=100,
    )


@pytest.fixture
def test_app(
    test_settings: Settings,
    mock_fetch_result: FetchResult,
) -> TestClient:
    """Create test app with mocked dependencies."""
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(fetch_router)

    # Mock fetcher
    fetcher = MagicMock(spec=PageFetcher)
    fetcher.is_connected = True
    fetcher.active_pages = 0
    fetcher.fetch = AsyncMock(return_value=mock_fetch_result)
    fetcher.screenshot_to_base64 = PageFetcher.screenshot_to_base64

    # Mock cache
    cache = MagicMock(spec=CacheLayer)
    cache.is_connected = True
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.invalidate = AsyncMock(return_value=True)

    # Real extractor
    extractor = ContentExtractor(test_settings)

    app.state.fetcher = fetcher
    app.state.cache = cache
    app.state.extractor = extractor
    app.state.start_time = 0.0

    return TestClient(app)


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_ok(self, test_app: TestClient) -> None:
        """Should return healthy status."""
        resp = test_app.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "iris"
        assert data["version"] == "0.1.0"

    def test_health_browser_status(self, test_app: TestClient) -> None:
        """Should report browser connection status."""
        resp = test_app.get("/health")
        data = resp.json()
        assert data["browser_connected"] is True

    def test_health_cache_status(self, test_app: TestClient) -> None:
        """Should report cache connection status."""
        resp = test_app.get("/health")
        data = resp.json()
        assert data["cache_connected"] is True

    def test_health_uptime(self, test_app: TestClient) -> None:
        """Should report uptime."""
        resp = test_app.get("/health")
        data = resp.json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0


class TestFetchEndpoint:
    """Tests for POST /fetch."""

    def test_fetch_success(self, test_app: TestClient) -> None:
        """Should fetch a page and return extracted content."""
        resp = test_app.post("/fetch", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://example.com"
        assert data["status_code"] == 200
        assert data["content_text"] is not None
        assert data["error"] is None

    def test_fetch_with_metadata(self, test_app: TestClient) -> None:
        """Should extract metadata by default."""
        resp = test_app.post("/fetch", json={"url": "https://example.com"})
        data = resp.json()
        assert data["metadata"] is not None
        assert data["metadata"]["title"] == "Test"

    def test_fetch_without_text(self, test_app: TestClient) -> None:
        """Should skip text extraction when disabled."""
        resp = test_app.post(
            "/fetch",
            json={"url": "https://example.com", "extract_text": False},
        )
        data = resp.json()
        assert data["content_text"] is None

    def test_fetch_without_metadata(self, test_app: TestClient) -> None:
        """Should skip metadata when disabled."""
        resp = test_app.post(
            "/fetch",
            json={"url": "https://example.com", "extract_metadata": False},
        )
        data = resp.json()
        assert data["metadata"] is None

    def test_fetch_with_links(self, test_app: TestClient) -> None:
        """Should extract links when enabled."""
        resp = test_app.post(
            "/fetch",
            json={"url": "https://example.com", "extract_links": True},
        )
        data = resp.json()
        assert data["links"] is not None
        assert len(data["links"]) >= 1

    def test_fetch_error_handling(self, test_app: TestClient) -> None:
        """Should handle fetch errors gracefully."""
        test_app.app.state.fetcher.fetch = AsyncMock(  # type: ignore[union-attr]
            return_value=FetchResult(
                url="https://example.com",
                status_code=0,
                html="",
                error=FetchError(
                    type=FetchErrorType.CONNECTION_ERROR,
                    message="Connection refused",
                    retryable=True,
                ),
                fetch_time_ms=50,
            )
        )
        resp = test_app.post("/fetch", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is not None
        assert data["error"]["type"] == "connection_error"
        assert data["error"]["message"] == "Connection refused"
        assert data["status_code"] == 0

    def test_fetch_browser_unavailable(self, test_app: TestClient) -> None:
        """Should return 503 when browser is not connected."""
        test_app.app.state.fetcher.is_connected = False  # type: ignore[union-attr]
        resp = test_app.post("/fetch", json={"url": "https://example.com"})
        assert resp.status_code == 503

    def test_fetch_cached_response(self, test_app: TestClient) -> None:
        """Should return cached response when available."""
        cached_resp = FetchResponse(
            url="https://example.com",
            status_code=200,
            content_text="Cached content",
            content_length=14,
            fetch_time_ms=0,
            cached=False,
        )
        test_app.app.state.cache.get = AsyncMock(return_value=cached_resp)  # type: ignore[union-attr]

        resp = test_app.post("/fetch", json={"url": "https://example.com"})
        data = resp.json()
        assert data["cached"] is True
        assert data["content_text"] == "Cached content"

    def test_fetch_cache_bypass(self, test_app: TestClient) -> None:
        """Should bypass cache when cache=false."""
        test_app.post(
            "/fetch",
            json={"url": "https://example.com", "cache": False},
        )
        # Cache.get should not be called
        test_app.app.state.cache.get.assert_not_called()  # type: ignore[union-attr]

    def test_fetch_content_length(self, test_app: TestClient) -> None:
        """Should report content length."""
        resp = test_app.post("/fetch", json={"url": "https://example.com"})
        data = resp.json()
        assert data["content_length"] >= 0


class TestBatchEndpoint:
    """Tests for POST /batch."""

    def test_batch_single(self, test_app: TestClient) -> None:
        """Should handle a single request in batch."""
        resp = test_app.post(
            "/batch",
            json={"requests": [{"url": "https://example.com"}]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        assert data["total_time_ms"] >= 0

    def test_batch_multiple(self, test_app: TestClient) -> None:
        """Should handle multiple requests in batch."""
        resp = test_app.post(
            "/batch",
            json={
                "requests": [
                    {"url": "https://example.com/1"},
                    {"url": "https://example.com/2"},
                    {"url": "https://example.com/3"},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 3

    def test_batch_max_limit(self, test_app: TestClient) -> None:
        """Should reject batch with more than 10 requests."""
        resp = test_app.post(
            "/batch",
            json={"requests": [{"url": f"https://example.com/{i}"} for i in range(11)]},
        )
        assert resp.status_code == 422  # Validation error

    def test_batch_empty(self, test_app: TestClient) -> None:
        """Should reject empty batch."""
        resp = test_app.post("/batch", json={"requests": []})
        assert resp.status_code == 422

    def test_batch_browser_unavailable(self, test_app: TestClient) -> None:
        """Should return 503 when browser is not connected."""
        test_app.app.state.fetcher.is_connected = False  # type: ignore[union-attr]
        resp = test_app.post(
            "/batch",
            json={"requests": [{"url": "https://example.com"}]},
        )
        assert resp.status_code == 503


class TestCacheEndpoint:
    """Tests for DELETE /cache/{url_hash}."""

    def test_invalidate_success(self, test_app: TestClient) -> None:
        """Should invalidate a cached entry."""
        resp = test_app.delete("/cache/abc123hash")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is True

    def test_invalidate_not_found(self, test_app: TestClient) -> None:
        """Should return deleted=false for missing key."""
        test_app.app.state.cache.invalidate = AsyncMock(return_value=False)  # type: ignore[union-attr]
        resp = test_app.delete("/cache/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] is False
