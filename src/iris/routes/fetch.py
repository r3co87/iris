"""Fetch endpoints — single page and batch fetching."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, HTTPException, Request

from iris.cache import CacheLayer, make_cache_key
from iris.extractor import ContentExtractor
from iris.fetcher import PageFetcher
from iris.logging import get_logger
from iris.schemas import (
    BatchFetchRequest,
    BatchFetchResponse,
    FetchRequest,
    FetchResponse,
)

logger = get_logger(__name__)

router = APIRouter()


async def _do_fetch(
    request: FetchRequest,
    fetcher: PageFetcher,
    extractor: ContentExtractor,
    cache: CacheLayer,
) -> FetchResponse:
    """Execute a single fetch request with caching, extraction, and error handling."""
    # Check cache
    cache_key = make_cache_key(
        request.url,
        extract_text=request.extract_text,
        extract_links=request.extract_links,
        extract_metadata=request.extract_metadata,
        screenshot=request.screenshot,
    )

    if request.cache:
        cached = await cache.get(cache_key)
        if cached is not None:
            cached.cached = True
            return cached

    # Fetch page
    result = await fetcher.fetch(
        url=request.url,
        wait_for_selector=request.wait_for_selector,
        wait_after_load_ms=request.wait_after_load_ms,
        timeout_ms=request.timeout_ms,
        take_screenshot=request.screenshot,
        headers=request.headers,
    )

    # Handle fetch errors
    if result.error:
        return FetchResponse(
            url=result.url,
            status_code=result.status_code,
            error=result.error,
            fetch_time_ms=result.fetch_time_ms,
        )

    # Extract content
    content_text: str | None = None
    if request.extract_text:
        content_text = extractor.extract_text(result.html)

    metadata = None
    if request.extract_metadata:
        metadata = extractor.extract_metadata(result.html, result.url)

    links = None
    if request.extract_links:
        links = extractor.extract_links(result.html, result.url)

    screenshot_base64: str | None = None
    if result.screenshot_bytes:
        screenshot_base64 = PageFetcher.screenshot_to_base64(result.screenshot_bytes)

    response = FetchResponse(
        url=result.url,
        status_code=result.status_code,
        content_text=content_text,
        metadata=metadata,
        links=links,
        screenshot_base64=screenshot_base64,
        content_length=len(content_text) if content_text else 0,
        fetch_time_ms=result.fetch_time_ms,
        cached=False,
    )

    # Cache the response (without screenshot to save space)
    if request.cache and not result.error:
        cache_response = response.model_copy()
        cache_response.screenshot_base64 = None
        await cache.set(cache_key, cache_response)

    return response


@router.post("/fetch", response_model=FetchResponse)
async def fetch_page(request: Request, body: FetchRequest) -> FetchResponse:
    """Fetch a single web page with JS rendering."""
    fetcher: PageFetcher = request.app.state.fetcher
    extractor: ContentExtractor = request.app.state.extractor
    cache: CacheLayer = request.app.state.cache

    if not fetcher.is_connected:
        raise HTTPException(status_code=503, detail="Browser not available")

    return await _do_fetch(body, fetcher, extractor, cache)


@router.post("/batch", response_model=BatchFetchResponse)
async def batch_fetch(request: Request, body: BatchFetchRequest) -> BatchFetchResponse:
    """Fetch multiple URLs concurrently (max 10)."""
    fetcher: PageFetcher = request.app.state.fetcher
    extractor: ContentExtractor = request.app.state.extractor
    cache: CacheLayer = request.app.state.cache

    if not fetcher.is_connected:
        raise HTTPException(status_code=503, detail="Browser not available")

    start_time = time.monotonic()

    tasks = [_do_fetch(req, fetcher, extractor, cache) for req in body.requests]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    responses: list[FetchResponse] = []
    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            responses.append(
                FetchResponse(
                    url=body.requests[i].url,
                    status_code=0,
                    error=str(result),
                )
            )
        else:
            resp: FetchResponse = result
            responses.append(resp)

    total_ms = int((time.monotonic() - start_time) * 1000)
    return BatchFetchResponse(results=responses, total_time_ms=total_ms)


@router.delete("/cache/{url_hash}")
async def invalidate_cache(request: Request, url_hash: str) -> dict[str, bool]:
    """Invalidate a cached entry by its URL hash."""
    cache: CacheLayer = request.app.state.cache
    deleted = await cache.invalidate(url_hash)
    return {"deleted": deleted}
