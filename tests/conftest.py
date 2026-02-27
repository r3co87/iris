"""Shared test fixtures for Iris."""

from __future__ import annotations

from unittest.mock import patch

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from iris.cache import CacheLayer
from iris.config import Settings
from iris.extractor import ContentExtractor
from iris.fetcher import FetchResult, PageFetcher
from iris.main import create_app


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        TESTING_MODE=True,
        CACHE_ENABLED=True,
        REDIS_URL="redis://localhost:6379/4",
        HEADLESS=True,
        MAX_CONCURRENT_PAGES=2,
        RESPECT_ROBOTS_TXT=False,
        MAX_CONTENT_LENGTH=10000,
    )


@pytest.fixture
def extractor(settings: Settings) -> ContentExtractor:
    """Create a content extractor."""
    return ContentExtractor(settings)


@pytest.fixture
def mock_fetcher(settings: Settings) -> PageFetcher:
    """Create a mock page fetcher."""
    fetcher = PageFetcher(settings)
    fetcher._connected = True
    return fetcher


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """Create a fake Redis instance."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def cache(settings: Settings, fake_redis: fakeredis.aioredis.FakeRedis) -> CacheLayer:
    """Create a cache layer with fake Redis."""
    layer = CacheLayer(settings)
    layer._client = fake_redis  # type: ignore[assignment]
    layer._connected = True
    return layer


@pytest.fixture
def sample_html() -> str:
    """Sample HTML page for extraction tests."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Test Article Title</title>
    <meta name="description" content="A test article description">
    <meta name="author" content="Test Author">
    <meta property="og:title" content="OG Test Title">
    <meta property="og:description" content="OG test description">
    <meta property="og:image" content="/images/og.png">
    <meta property="article:published_time" content="2024-01-15T10:00:00Z">
    <link rel="canonical" href="https://example.com/article">
</head>
<body>
    <nav><a href="/">Home</a></nav>
    <main>
        <h1>Test Article Title</h1>
        <p>This is the first paragraph of the test article.
        It contains important information about testing.</p>
        <p>This is the second paragraph with more details
        about content extraction testing.</p>
        <a href="/internal-page">Internal Link</a>
        <a href="https://external.com/page">External Link</a>
        <a href="https://example.com/another">Another Internal</a>
    </main>
    <script>console.log("should be removed");</script>
    <style>.hidden { display: none; }</style>
    <footer><p>Footer content</p></footer>
</body>
</html>"""


@pytest.fixture
def sample_fetch_result(sample_html: str) -> FetchResult:
    """Sample FetchResult for testing."""
    return FetchResult(
        url="https://example.com/article",
        status_code=200,
        html=sample_html,
        fetch_time_ms=150,
    )


@pytest.fixture
def app(
    settings: Settings,
    mock_fetcher: PageFetcher,
    cache: CacheLayer,
    extractor: ContentExtractor,
) -> TestClient:
    """Create a test client with mocked dependencies."""
    application = create_app(settings)

    # Override lifespan by directly setting state
    application.state.fetcher = mock_fetcher
    application.state.cache = cache
    application.state.extractor = extractor
    application.state.start_time = 0.0

    # Patch out lifespan to avoid starting Playwright
    with patch("iris.main.lifespan") as mock_lifespan:

        async def _no_op_lifespan(app):  # type: ignore[no-untyped-def]
            yield

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake_lifespan(app):  # type: ignore[no-untyped-def]
            app.state.fetcher = mock_fetcher
            app.state.cache = cache
            app.state.extractor = extractor
            app.state.start_time = 0.0
            yield

        mock_lifespan.side_effect = fake_lifespan

        # Recreate app with patched lifespan
        application = create_app(settings)
        application.state.fetcher = mock_fetcher
        application.state.cache = cache
        application.state.extractor = extractor
        application.state.start_time = 0.0

        return TestClient(application, raise_server_exceptions=False)
