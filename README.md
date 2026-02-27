# Iris — Web Automation Engine

Playwright-based web fetching service for the **Cortex AI Personal Assistant** ecosystem. Iris provides full-page fetching with JavaScript rendering, content extraction, and caching.

## Features

- **JS Rendering** — Playwright Chromium headless for SPA and dynamic pages
- **Content Extraction** — trafilatura + BeautifulSoup for clean text, metadata, links
- **Structured Data** — JSON-LD and Schema.org microdata extraction
- **PDF Extraction** — Text and metadata extraction via pymupdf
- **Redis Cache** — SHA256-keyed response cache with configurable TTL
- **Batch Fetching** — Up to 10 URLs concurrently with semaphore control
- **Rate Limiting** — Redis-based Token Bucket per domain with memory fallback
- **robots.txt** — Redis-cached compliance with 24h TTL
- **Smart Wait Strategies** — load, networkidle, selector, timeout, domcontentloaded
- **Retry Logic** — Exponential backoff for transient errors (timeout, 429, 5xx)
- **Error Classification** — Typed errors with retryable flag and HTTP status
- **Content Type Detection** — Auto-handles HTML, PDF, JSON, text, images
- **Screenshots** — Full-page PNG screenshots as base64

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Run locally
IRIS_TESTING_MODE=true PYTHONPATH=src uvicorn iris.main:app --port 8060

# Run tests
PYTHONPATH=src pytest tests/ -v
```

## API

### `POST /fetch`

```json
{
    "url": "https://example.com",
    "extract_text": true,
    "extract_metadata": true,
    "extract_links": false,
    "screenshot": false,
    "cache": true,
    "wait_strategy": "load",
    "wait_for_selector": null,
    "wait_after_load_ms": null,
    "timeout_ms": null,
    "headers": null
}
```

Response includes typed error classification:

```json
{
    "url": "https://example.com",
    "status_code": 200,
    "content_text": "...",
    "metadata": { "title": "...", "pdf_pages": null },
    "structured_data": { "json_ld": [...], "schema_org_types": [...] },
    "error": { "type": "timeout", "message": "...", "retryable": true }
}
```

### `POST /batch`

```json
{
    "requests": [
        {"url": "https://example.com/1"},
        {"url": "https://example.com/2"}
    ]
}
```

### `GET /health`

Returns service health including browser and cache status.

### `DELETE /cache/{url_hash}`

Invalidate a cached response by its SHA256 hash.

## Docker

```bash
docker build -t iris .
docker run -p 8060:8060 -e IRIS_TESTING_MODE=true iris
```

## Configuration

All environment variables are prefixed with `IRIS_`. See `CLAUDE.md` for the full configuration reference.

## Part of the Cortex Ecosystem

Iris is consumed by Oracle (Deep Research), Cortex Agent, and Forge for web content retrieval with full JavaScript rendering support.
