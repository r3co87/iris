# Iris — Web Automation Engine

Iris ist ein Playwright-basierter Web Automation Satellite im Cortex-Ökosystem, der Full-Page Fetching mit JavaScript-Rendering für Oracle (Deep Research) und andere Satellites bereitstellt.

## Architektur

```
src/iris/
├── __init__.py              # Version
├── main.py                  # FastAPI App + Lifespan (Browser Lifecycle + Sentinel Init)
├── config.py                # Settings via Pydantic BaseSettings (IRIS_ prefix)
├── schemas.py               # Request/Response Models, Error Types, Enums
├── fetcher.py               # PageFetcher — Playwright, Retry, Content Type Detection
├── extractor.py             # ContentExtractor — HTML → Text, Metadata, Links, Structured Data
├── pdf_extractor.py         # PdfExtractor — PDF → Text + Metadata (pymupdf)
├── robots_handler.py        # RobotsHandler — robots.txt mit Redis Cache
├── wait_strategy.py         # SmartWaiter — 5 Wait-Strategien für dynamischen Content
├── rate_limiter.py          # DomainRateLimiter — Token Bucket per Domain (Redis)
├── cache.py                 # Redis Cache Layer (DB 4) mit Graceful Degradation
├── logging.py               # Structured JSON Logging
├── healthcheck.py           # Docker Healthcheck Script
├── routes/
│   ├── health.py            # GET /health
│   └── fetch.py             # POST /fetch, POST /batch, DELETE /cache/{hash}
└── sentinel_sdk/            # Sentinel mTLS + JWT Client (kopiert von Hermes)
    ├── client.py
    └── exceptions.py
```

## API Endpoints

| Method | Path              | Beschreibung                          |
|--------|-------------------|---------------------------------------|
| GET    | `/health`         | Service Status, Browser, Cache Stats  |
| POST   | `/fetch`          | Einzelne Seite fetchen mit JS Render  |
| POST   | `/batch`          | Bis zu 10 URLs parallel fetchen       |
| DELETE | `/cache/{hash}`   | Cache-Eintrag invalidieren            |

### FetchRequest Parameter

| Feld               | Typ            | Default  | Beschreibung                        |
|--------------------|----------------|----------|-------------------------------------|
| `url`              | `str`          | required | URL to fetch                        |
| `wait_strategy`    | `WaitStrategy` | `load`   | load/networkidle/selector/timeout/domcontentloaded |
| `wait_for_selector`| `str?`         | null     | CSS Selector (auto-switches to SELECTOR strategy) |
| `wait_after_load_ms`| `int?`        | null     | Extra wait after page load          |
| `extract_text`     | `bool`         | true     | Extract clean text                  |
| `extract_links`    | `bool`         | false    | Extract links                       |
| `extract_metadata` | `bool`         | true     | Extract meta tags                   |
| `screenshot`       | `bool`         | false    | Take screenshot                     |
| `timeout_ms`       | `int?`         | null     | Override timeout                    |
| `cache`            | `bool`         | true     | Use cache                           |
| `headers`          | `dict?`        | null     | Custom HTTP headers                 |

### Error Types (FetchErrorType)

| Type                        | Retryable | Beschreibung                    |
|-----------------------------|-----------|----------------------------------|
| `timeout`                   | ja        | Navigation/Request Timeout       |
| `dns_error`                 | ja        | DNS Resolution fehlgeschlagen    |
| `connection_error`          | ja        | Connection refused/reset         |
| `ssl_error`                 | nein      | SSL/Certificate Fehler           |
| `blocked_by_robots_txt`     | nein      | robots.txt blockiert             |
| `rate_limited`              | ja        | HTTP 429 Too Many Requests       |
| `unsupported_content_type`  | nein      | Nicht unterstützter Content-Type |
| `invalid_url`               | nein      | Ungültige URL                    |
| `http_error`                | variabel  | 4xx/5xx (502/503/504 retryable)  |
| `content_too_large`         | nein      | Content zu gross                 |
| `browser_error`             | nein      | Playwright/Browser Fehler        |

### Content Type Handling

| Content-Type       | Handling                                        |
|--------------------|-------------------------------------------------|
| `text/html`        | Playwright Rendering + Content Extraction        |
| `application/pdf`  | PDF Extractor (pymupdf) → Text + Metadata        |
| `application/json` | Pretty-printed als content_text                  |
| `text/plain`       | Direkt als content_text                          |
| `image/*`          | Nur Metadata (URL, Status), kein Text            |
| Andere             | Error: unsupported_content_type                  |

## Konfiguration (Env-Vars)

Alle Variablen haben das Prefix `IRIS_`.

| Variable                          | Default                              | Beschreibung                        |
|-----------------------------------|--------------------------------------|-------------------------------------|
| `IRIS_HOST`                       | `0.0.0.0`                           | Bind Host                           |
| `IRIS_PORT`                       | `8060`                               | Service Port                        |
| `IRIS_LOG_LEVEL`                  | `INFO`                               | Log Level                           |
| `IRIS_BROWSER_TYPE`               | `chromium`                           | Browser (chromium/firefox/webkit)   |
| `IRIS_HEADLESS`                   | `true`                               | Headless Mode                       |
| `IRIS_PAGE_TIMEOUT_MS`            | `30000`                              | Max Timeout pro Seite (ms)          |
| `IRIS_WAIT_AFTER_LOAD_MS`         | `2000`                               | Wait nach Page Load (ms)            |
| `IRIS_MAX_CONCURRENT_PAGES`       | `3`                                  | Max parallele Tabs                  |
| `IRIS_USER_AGENT`                 | `Cortex-Iris/1.0 (Research Bot)`     | User Agent String                   |
| `IRIS_MAX_CONTENT_LENGTH`         | `500000`                             | Max extracted text (~500KB)         |
| `IRIS_REDIS_URL`                  | `redis://redis:6379/4`               | Redis Cache (DB 4)                  |
| `IRIS_CACHE_TTL_SECONDS`          | `3600`                               | Cache TTL (1h)                      |
| `IRIS_CACHE_ENABLED`              | `true`                               | Cache an/aus                        |
| `IRIS_MIN_DELAY_BETWEEN_REQUESTS_MS` | `1000`                            | Rate Limit pro Domain (ms)          |
| `IRIS_RATE_LIMIT_BURST`           | `3`                                  | Burst-Allowance pro Domain          |
| `IRIS_RESPECT_ROBOTS_TXT`         | `true`                               | robots.txt respektieren             |
| `IRIS_ROBOTS_TXT_CACHE_TTL`       | `86400`                              | robots.txt Cache TTL (24h)          |
| `IRIS_MAX_RETRIES`                | `3`                                  | Max Retries bei transienten Fehlern |
| `IRIS_TESTING_MODE`               | `false`                              | Testing Mode (kein mTLS)            |
| `IRIS_SENTINEL_URL`               | `https://sentinel:8443`              | Sentinel Gateway URL                |

## Dependencies

- `pymupdf` — PDF Text Extraction (schnell, C-basiert)
- `playwright` — Headless Browser Automation
- `trafilatura` + `beautifulsoup4` — HTML Content Extraction
- `redis` — Cache + Rate Limiter + robots.txt Cache
- `httpx` — HTTP Client für robots.txt Fetching

## Docker

```dockerfile
# Build
docker build -t iris .

# Run
docker run -p 8060:8060 -e IRIS_TESTING_MODE=true iris
```

Healthcheck: `python -m iris.healthcheck` (prüft `GET /health`)

## Tests

```bash
# Alle Tests (184 Tests)
PYTHONPATH=src pytest tests/ -v

# Mit Coverage
PYTHONPATH=src pytest tests/ -v --cov=iris --cov-report=term-missing

# Lint + Format
ruff check src/ tests/
ruff format --check src/ tests/

# Type Check
PYTHONPATH=src mypy src/iris/
```

**Test-Module:**
- `test_extractor.py` — HTML → Text, Metadata, Links, Structured Data
- `test_cache.py` — Redis Set/Get/Invalidate, TTL, Graceful Degradation
- `test_fetcher.py` — Playwright-Mocks, Timeout, Semaphore, Content Type
- `test_routes.py` — FastAPI TestClient, Health, Fetch, Batch, Cache
- `test_pdf_extractor.py` — PDF → Text, Metadata, Multi-Page, Error Handling
- `test_robots_handler.py` — robots.txt Parsing, Redis Cache, Graceful Degradation
- `test_wait_strategy.py` — Alle 5 Wait-Strategien (gemockt)
- `test_rate_limiter.py` — Token Bucket, Per-Domain, Burst, Redis Fallback
- `test_retry.py` — Retry bei transienten Fehlern, kein Retry bei permanenten
- `test_content_type.py` — HTML/PDF/JSON/Text/Image/Unsupported
- `test_structured_data.py` — JSON-LD, Schema.org Microdata
- `test_error_classification.py` — Alle FetchErrorType Varianten
- `test_e2e_iris.py` — E2E-Tests: Sentinel-Integration, Health, Fetch, Batch, Cache

## Ökosystem-Kontext

- **Sentinel** (:8443) — Iris registriert sich als `satellite-iris` mit mTLS + JWT
- **Oracle** (:8010) — Hauptkonsument, nutzt Iris für Deep Web Research
- **Cortex Agent** (:8020) — Hat `iris_fetch` und `iris_screenshot` als Tools
- **Redis** (DB 4) — Shared Cache für gefetchte Seiten
- **Forge** (:8050) — Kann Iris für Web-Scraping in Code-Execution nutzen

## Bekannte Issues / TODOs

- [x] Sentinel-Integration vollständig (Paket 3)
- [ ] Stealth-Mode (Anti-Bot-Detection)
- [ ] Proxy-Support
- [ ] Cookie/Session Management
- [x] PDF-Download Support (Paket 2)
- [ ] Recursive Crawling (Multi-Page)
- [ ] JavaScript Execution API (custom JS auf Seiten ausführen)

### Aktueller Roadmap-Status

Zuletzt abgeschlossen: Iris Paket 3 — Cortex Integration + Docker Compose + Sentinel
Nächster Schritt: Stealth-Mode, Proxy-Support, oder Recursive Crawling
Datum: 2026-02-27
