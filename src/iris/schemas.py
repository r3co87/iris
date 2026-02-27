"""Pydantic request/response models for Iris."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FetchRequest(BaseModel):
    """Request to fetch a web page."""

    url: str = Field(..., description="URL to fetch")
    wait_for_selector: str | None = Field(
        None, description="CSS selector to wait for before extraction"
    )
    wait_after_load_ms: int | None = Field(
        None, description="Override default wait time after page load (ms)"
    )
    extract_text: bool = Field(True, description="Extract clean text from page")
    extract_links: bool = Field(False, description="Extract links from page")
    extract_metadata: bool = Field(True, description="Extract meta tags from page")
    screenshot: bool = Field(False, description="Take screenshot (base64 PNG)")
    timeout_ms: int | None = Field(None, description="Override default timeout (ms)")
    cache: bool = Field(True, description="Use cache for this request")
    headers: dict[str, str] | None = Field(None, description="Custom HTTP headers")


class BatchFetchRequest(BaseModel):
    """Request to fetch multiple URLs."""

    requests: list[FetchRequest] = Field(
        ..., min_length=1, max_length=10, description="List of fetch requests (1-10)"
    )


class PageMetadata(BaseModel):
    """Extracted page metadata."""

    title: str | None = None
    description: str | None = None
    og_title: str | None = None
    og_description: str | None = None
    og_image: str | None = None
    language: str | None = None
    canonical_url: str | None = None
    author: str | None = None
    published_date: str | None = None


class ExtractedLink(BaseModel):
    """A link extracted from a page."""

    url: str
    text: str
    is_external: bool


class FetchResponse(BaseModel):
    """Response from a page fetch operation."""

    url: str
    status_code: int
    content_text: str | None = None
    content_html: str | None = None
    metadata: PageMetadata | None = None
    links: list[ExtractedLink] | None = None
    screenshot_base64: str | None = None
    content_length: int = 0
    fetch_time_ms: int = 0
    cached: bool = False
    error: str | None = None


class BatchFetchResponse(BaseModel):
    """Response from a batch fetch operation."""

    results: list[FetchResponse]
    total_time_ms: int = 0


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    service: str = "iris"
    version: str = "0.1.0"
    browser_connected: bool = False
    cache_connected: bool = False
    active_pages: int = 0
    uptime_seconds: float = 0.0
