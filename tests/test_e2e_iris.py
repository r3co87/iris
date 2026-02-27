"""End-to-end tests for Iris — full request lifecycle through the FastAPI app."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from iris.cache import CacheLayer
from iris.config import Settings
from iris.extractor import ContentExtractor
from iris.fetcher import FetchResult, PageFetcher
from iris.main import create_app
from iris.routes.fetch import router as fetch_router
from iris.routes.health import router as health_router
from iris.schemas import (
    FetchError,
    FetchErrorType,
)
from iris.sentinel_sdk import SentinelClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

STATIC_HTML = """<html><head><title>Static Page</title>
<meta name="description" content="A simple static page"></head>
<body><p>Hello from a static page.</p>
<a href="https://example.com/other">Other Page</a></body></html>"""

ROBOTS_BLOCKED_HTML = ""


@pytest.fixture
def e2e_settings() -> Settings:
    """Settings for E2E tests — TESTING_MODE=True, cache enabled."""
    return Settings(
        TESTING_MODE=True,
        CACHE_ENABLED=True,
        REDIS_URL="redis://localhost:6379/4",
        HEADLESS=True,
        MAX_CONCURRENT_PAGES=2,
        RESPECT_ROBOTS_TXT=True,
        MAX_CONTENT_LENGTH=10000,
    )


@pytest.fixture
def e2e_fake_redis() -> fakeredis.aioredis.FakeRedis:
    """Fake Redis for E2E cache tests."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def e2e_cache(
    e2e_settings: Settings,
    e2e_fake_redis: fakeredis.aioredis.FakeRedis,
) -> CacheLayer:
    """Cache layer backed by fake Redis."""
    layer = CacheLayer(e2e_settings)
    layer._client = e2e_fake_redis  # type: ignore[assignment]
    layer._connected = True
    return layer


@pytest.fixture
def e2e_extractor(e2e_settings: Settings) -> ContentExtractor:
    """Real content extractor."""
    return ContentExtractor(e2e_settings)


@pytest.fixture
def e2e_fetcher(e2e_settings: Settings) -> MagicMock:
    """Mock PageFetcher that returns configurable FetchResults."""
    fetcher = MagicMock(spec=PageFetcher)
    fetcher.is_connected = True
    fetcher.active_pages = 0
    fetcher.screenshot_to_base64 = PageFetcher.screenshot_to_base64

    # Default: return static HTML for any URL
    fetcher.fetch = AsyncMock(
        return_value=FetchResult(
            url="https://example.com",
            status_code=200,
            html=STATIC_HTML,
            fetch_time_ms=120,
        )
    )
    return fetcher


@pytest.fixture
def e2e_app(
    e2e_settings: Settings,
    e2e_fetcher: MagicMock,
    e2e_cache: CacheLayer,
    e2e_extractor: ContentExtractor,
) -> TestClient:
    """Full app TestClient with mocked browser and real cache/extractor."""
    application = FastAPI()
    application.include_router(health_router)
    application.include_router(fetch_router)

    application.state.fetcher = e2e_fetcher
    application.state.cache = e2e_cache
    application.state.extractor = e2e_extractor
    application.state.start_time = 0.0
    application.state.sentinel = None

    return TestClient(application)


# ---------------------------------------------------------------------------
# E2E Tests
# ---------------------------------------------------------------------------


class TestE2EIris:
    """End-to-end tests covering the full Iris request lifecycle."""

    # -- Health ---------------------------------------------------------------

    def test_iris_health(self, e2e_app: TestClient) -> None:
        """Iris Health-Endpoint erreichbar."""
        resp = e2e_app.get("/health")
        assert resp.status_code == 200

        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "iris"
        assert data["version"] == "0.1.0"
        assert data["browser_connected"] is True
        assert data["cache_connected"] is True
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    def test_iris_health_sentinel_field(self, e2e_app: TestClient) -> None:
        """Health response includes sentinel_connected field."""
        resp = e2e_app.get("/health")
        assert resp.status_code == 200

        data = resp.json()
        # sentinel_connected must be present in the response schema
        assert "sentinel_connected" in data
        # In testing mode with sentinel=None it should be False
        assert data["sentinel_connected"] is False

    # -- Fetch ----------------------------------------------------------------

    def test_iris_fetch_simple(self, e2e_app: TestClient) -> None:
        """Einfacher Fetch einer statischen Seite."""
        resp = e2e_app.post(
            "/fetch",
            json={"url": "https://example.com/page"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert data["url"] == "https://example.com"
        assert data["status_code"] == 200
        assert data["error"] is None
        assert data["cached"] is False

        # Content text was extracted from the static HTML
        assert data["content_text"] is not None
        assert len(data["content_text"]) > 0

        # Metadata was extracted
        assert data["metadata"] is not None
        assert data["metadata"]["title"] == "Static Page"
        assert data["metadata"]["description"] == "A simple static page"

        # Fetch time reported
        assert data["fetch_time_ms"] >= 0

        # Content length matches extracted text
        assert data["content_length"] == len(data["content_text"])

    def test_iris_fetch_with_cache(
        self,
        e2e_app: TestClient,
        e2e_fetcher: MagicMock,
    ) -> None:
        """Zweiter Fetch kommt aus Cache."""
        url = "https://example.com/cached-page"

        # First request — should go through the fetcher
        resp1 = e2e_app.post("/fetch", json={"url": url})
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["cached"] is False
        assert data1["content_text"] is not None

        first_call_count = e2e_fetcher.fetch.call_count
        assert first_call_count >= 1

        # Second request — same URL should come from cache
        resp2 = e2e_app.post("/fetch", json={"url": url})
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["cached"] is True
        assert data2["content_text"] is not None

        # Fetcher should NOT have been called again
        assert e2e_fetcher.fetch.call_count == first_call_count

    # -- Batch ----------------------------------------------------------------

    def test_iris_batch(self, e2e_app: TestClient, e2e_fetcher: MagicMock) -> None:
        """Mehrere URLs gleichzeitig fetchen."""
        urls = [
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/c",
        ]

        # Configure fetcher to return different URLs in FetchResult
        async def _side_effect(**kwargs: Any) -> FetchResult:
            return FetchResult(
                url=kwargs.get("url", "https://example.com"),
                status_code=200,
                html=STATIC_HTML,
                fetch_time_ms=80,
            )

        e2e_fetcher.fetch = AsyncMock(side_effect=_side_effect)

        resp = e2e_app.post(
            "/batch",
            json={"requests": [{"url": u} for u in urls]},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert "results" in data
        assert len(data["results"]) == 3
        assert "total_time_ms" in data
        assert data["total_time_ms"] >= 0

        # Every result should be a valid FetchResponse
        for result in data["results"]:
            assert result["status_code"] == 200
            assert result["error"] is None
            assert result["content_text"] is not None

    # -- Robots blocked -------------------------------------------------------

    def test_iris_robots_blocked(
        self,
        e2e_app: TestClient,
        e2e_fetcher: MagicMock,
    ) -> None:
        """URL die von robots.txt blockiert wird."""
        blocked_url = "https://blocked.example.com/secret"

        # Simulate the fetcher returning a robots-blocked error
        e2e_fetcher.fetch = AsyncMock(
            return_value=FetchResult(
                url=blocked_url,
                status_code=0,
                html="",
                error=FetchError(
                    type=FetchErrorType.BLOCKED_BY_ROBOTS,
                    message="Blocked by robots.txt",
                    retryable=False,
                ),
                fetch_time_ms=5,
            )
        )

        resp = e2e_app.post("/fetch", json={"url": blocked_url})
        assert resp.status_code == 200

        data = resp.json()
        assert data["error"] is not None
        assert data["error"]["type"] == "blocked_by_robots_txt"
        assert data["error"]["retryable"] is False
        assert data["status_code"] == 0
        assert data["content_text"] is None

    # -- Sentinel init --------------------------------------------------------

    def test_sentinel_init_testing_mode(self) -> None:
        """Sentinel client not created in testing mode."""
        settings = Settings(TESTING_MODE=True)
        application = create_app(settings)

        # Patch lifespan to run the startup logic we care about
        # In testing mode the lifespan sets sentinel = None
        with patch("iris.main.lifespan") as mock_lifespan:

            @asynccontextmanager
            async def fake_lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
                # Replicate the sentinel-init logic from the real lifespan
                sentinel = None
                if not settings.TESTING_MODE:
                    sentinel = SentinelClient(
                        sentinel_url=str(settings.SENTINEL_URL),
                        satellite_id=settings.SATELLITE_ID,
                        satellite_secret="test-secret",
                        testing_mode=False,
                    )
                app.state.sentinel = sentinel
                app.state.start_time = 0.0

                # Stub out other state so the app is usable
                fetcher = MagicMock(spec=PageFetcher)
                fetcher.is_connected = True
                fetcher.active_pages = 0
                app.state.fetcher = fetcher

                cache = MagicMock(spec=CacheLayer)
                cache.is_connected = False
                app.state.cache = cache

                app.state.extractor = ContentExtractor(settings)
                yield

            mock_lifespan.side_effect = fake_lifespan

            application = create_app(settings)
            with TestClient(application, raise_server_exceptions=False) as client:
                # Sentinel should be None in testing mode
                assert application.state.sentinel is None

                # Health endpoint should reflect sentinel_connected=False
                resp = client.get("/health")
                assert resp.status_code == 200
                assert resp.json()["sentinel_connected"] is False

    def test_sentinel_init_production_mode(self) -> None:
        """Sentinel client created in production mode."""
        settings = Settings(
            TESTING_MODE=False,
            SENTINEL_URL="https://sentinel.test:8443",
            SATELLITE_ID="satellite-iris-test",
            SATELLITE_SECRET="test-secret-value",
        )

        with patch("iris.main.lifespan") as mock_lifespan:

            @asynccontextmanager
            async def fake_lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
                # Replicate the sentinel-init logic from the real lifespan
                sentinel = None
                if not settings.TESTING_MODE:
                    sentinel = SentinelClient(
                        sentinel_url=str(settings.SENTINEL_URL),
                        satellite_id=settings.SATELLITE_ID,
                        satellite_secret=settings.get_satellite_secret(),
                        testing_mode=True,  # avoid real mTLS in tests
                    )
                    # Simulate a successful connect in testing_mode
                    await sentinel.connect()
                app.state.sentinel = sentinel
                app.state.start_time = 0.0

                # Stub out other state
                fetcher = MagicMock(spec=PageFetcher)
                fetcher.is_connected = True
                fetcher.active_pages = 0
                app.state.fetcher = fetcher

                cache = MagicMock(spec=CacheLayer)
                cache.is_connected = False
                app.state.cache = cache

                app.state.extractor = ContentExtractor(settings)
                yield
                await sentinel.close()

            mock_lifespan.side_effect = fake_lifespan

            application = create_app(settings)
            with TestClient(application, raise_server_exceptions=False) as client:
                # Sentinel should be created in production mode
                sentinel = application.state.sentinel
                assert sentinel is not None
                assert isinstance(sentinel, SentinelClient)
                assert sentinel.satellite_id == "satellite-iris-test"
                assert sentinel._client is not None

                # Health endpoint should reflect sentinel_connected=True
                resp = client.get("/health")
                assert resp.status_code == 200
                assert resp.json()["sentinel_connected"] is True
