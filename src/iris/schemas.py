"""Pydantic request/response models for Iris."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WaitStrategy(StrEnum):
    """Strategy for waiting on dynamic content."""

    LOAD = "load"
    NETWORKIDLE = "networkidle"
    SELECTOR = "selector"
    TIMEOUT = "timeout"
    DOMCONTENTLOADED = "domcontentloaded"


class FetchErrorType(StrEnum):
    """Classification of fetch errors."""

    TIMEOUT = "timeout"
    DNS_ERROR = "dns_error"
    CONNECTION_ERROR = "connection_error"
    SSL_ERROR = "ssl_error"
    BLOCKED_BY_ROBOTS = "blocked_by_robots_txt"
    RATE_LIMITED = "rate_limited"
    UNSUPPORTED_CONTENT_TYPE = "unsupported_content_type"
    INVALID_URL = "invalid_url"
    HTTP_ERROR = "http_error"
    CONTENT_TOO_LARGE = "content_too_large"
    BROWSER_ERROR = "browser_error"


class FetchError(BaseModel):
    """Structured error information for fetch failures."""

    type: FetchErrorType
    message: str
    retryable: bool
    http_status: int | None = None


class FetchRequest(BaseModel):
    """Request to fetch a web page."""

    url: str = Field(..., description="URL to fetch")
    wait_for_selector: str | None = Field(
        None, description="CSS selector to wait for before extraction"
    )
    wait_after_load_ms: int | None = Field(
        None, description="Override default wait time after page load (ms)"
    )
    wait_strategy: WaitStrategy = Field(
        WaitStrategy.LOAD, description="Wait strategy for dynamic content"
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
    pdf_pages: int | None = None
    pdf_author: str | None = None


class ExtractedLink(BaseModel):
    """A link extracted from a page."""

    url: str
    text: str
    is_external: bool


class StructuredData(BaseModel):
    """Structured data extracted from a page (JSON-LD, Schema.org)."""

    json_ld: list[dict[str, Any]] | None = None
    schema_org_types: list[str] | None = None


class PdfResult(BaseModel):
    """Result of PDF text extraction."""

    text: str
    pages: int
    title: str | None = None
    author: str | None = None
    created_date: str | None = None


class FetchResponse(BaseModel):
    """Response from a page fetch operation."""

    url: str
    status_code: int
    content_text: str | None = None
    content_html: str | None = None
    metadata: PageMetadata | None = None
    links: list[ExtractedLink] | None = None
    screenshot_base64: str | None = None
    structured_data: StructuredData | None = None
    content_length: int = 0
    fetch_time_ms: int = 0
    cached: bool = False
    error: FetchError | None = None


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
    sentinel_connected: bool = False
    active_pages: int = 0
    uptime_seconds: float = 0.0
