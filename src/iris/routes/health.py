"""Health check endpoint."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from iris.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Return service health status."""
    fetcher = request.app.state.fetcher
    cache = request.app.state.cache
    start_time: float = request.app.state.start_time

    cache_connected = cache.is_connected if cache else False

    return HealthResponse(
        status="ok",
        service="iris",
        version="0.1.0",
        browser_connected=fetcher.is_connected if fetcher else False,
        cache_connected=cache_connected,
        active_pages=fetcher.active_pages if fetcher else 0,
        uptime_seconds=round(time.monotonic() - start_time, 2),
    )
