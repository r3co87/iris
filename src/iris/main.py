"""FastAPI application factory with lifespan management."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from iris.cache import CacheLayer
from iris.config import Settings
from iris.extractor import ContentExtractor
from iris.fetcher import PageFetcher
from iris.logging import setup_logging
from iris.routes.fetch import router as fetch_router
from iris.routes.health import router as health_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of browser, cache, and other resources."""
    settings: Settings = app.state.settings
    setup_logging(settings.LOG_LEVEL)
    logger.info("Iris starting up (testing_mode=%s)", settings.TESTING_MODE)

    app.state.start_time = time.monotonic()

    # Cache
    cache = CacheLayer(settings)
    await cache.connect()
    app.state.cache = cache

    # Content Extractor
    extractor = ContentExtractor(settings)
    app.state.extractor = extractor

    # Page Fetcher (Playwright)
    fetcher = PageFetcher(settings)
    try:
        await fetcher.start()
    except Exception as e:
        logger.error("Failed to start browser: %s", e)
        # In testing mode, we allow startup without a browser
        if not settings.TESTING_MODE:
            raise
    app.state.fetcher = fetcher

    logger.info("Iris startup complete")
    yield

    # Shutdown
    await fetcher.close()
    await cache.close()
    logger.info("Iris shut down")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = Settings()

    app = FastAPI(
        title="Iris",
        version="0.1.0",
        description="Web Automation Engine for the Cortex ecosystem",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.include_router(health_router)
    app.include_router(fetch_router)

    return app


# Default app instance for uvicorn
app = create_app()
