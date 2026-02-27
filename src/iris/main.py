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
from iris.sentinel_sdk import SentinelClient

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of browser, cache, and other resources."""
    settings: Settings = app.state.settings
    setup_logging(settings.LOG_LEVEL)
    logger.info("Iris starting up (testing_mode=%s)", settings.TESTING_MODE)

    app.state.start_time = time.monotonic()

    # Sentinel client
    sentinel: SentinelClient | None = None
    if not settings.TESTING_MODE:
        satellite_secret = settings.get_satellite_secret()
        sentinel = SentinelClient(
            sentinel_url=str(settings.SENTINEL_URL),
            satellite_id=settings.SATELLITE_ID,
            satellite_secret=satellite_secret,
            cert_path=settings.SENTINEL_CERT_PATH,
            key_path=settings.SENTINEL_KEY_PATH,
            ca_path=settings.SENTINEL_CA_PATH,
            testing_mode=False,
        )
        try:
            await sentinel.connect()
            logger.info("Sentinel connected")
        except Exception as e:
            logger.error("Failed to connect to Sentinel: %s", e)
            # Continue startup — health endpoint will report degraded
    else:
        logger.info("Testing mode — skipping Sentinel")
    app.state.sentinel = sentinel

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
    if sentinel:
        await sentinel.close()
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
