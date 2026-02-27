# Iris — Web Automation Engine

Iris ist ein Playwright-basierter Web Automation Satellite im Cortex-Ökosystem, der Full-Page Fetching mit JavaScript-Rendering für Oracle (Deep Research) und andere Satellites bereitstellt.

## Architektur

```
src/iris/
├── __init__.py              # Version
├── main.py                  # FastAPI App + Lifespan (Browser Lifecycle)
├── config.py                # Settings via Pydantic BaseSettings (IRIS_ prefix)
├── schemas.py               # Request/Response Pydantic Models
├── fetcher.py               # PageFetcher — Playwright Chromium, Semaphore, Rate Limiting
├── extractor.py             # ContentExtractor — HTML → Clean Text (trafilatura + BS4)
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
| `IRIS_RESPECT_ROBOTS_TXT`         | `true`                               | robots.txt respektieren             |
| `IRIS_TESTING_MODE`               | `false`                              | Testing Mode (kein mTLS)            |
| `IRIS_SENTINEL_URL`               | `https://sentinel:8443`              | Sentinel Gateway URL                |

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
# Alle Tests (81 Tests)
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
- `test_extractor.py` — HTML → Text, Metadata, Links (verschiedene Seitentypen)
- `test_cache.py` — Redis Set/Get/Invalidate, TTL, Graceful Degradation
- `test_fetcher.py` — Playwright-Mocks, Timeout, Semaphore, Rate Limiting, robots.txt
- `test_routes.py` — FastAPI TestClient, Health, Fetch, Batch, Cache Endpoints

## Ökosystem-Kontext

- **Sentinel** (:8443) — Iris registriert sich als `satellite-iris` mit mTLS + JWT
- **Oracle** (:8010) — Hauptkonsument, nutzt Iris für Deep Web Research
- **Cortex Agent** (:8020) — Hat `iris_fetch` und `iris_screenshot` als Tools
- **Redis** (DB 4) — Shared Cache für gefetchte Seiten
- **Forge** (:8050) — Kann Iris für Web-Scraping in Code-Execution nutzen

## Bekannte Issues / TODOs

- [ ] Sentinel-Integration vollständig (Paket 3)
- [ ] Stealth-Mode (Anti-Bot-Detection)
- [ ] Proxy-Support
- [ ] Cookie/Session Management
- [ ] PDF-Download Support
- [ ] Recursive Crawling (Multi-Page)
- [ ] JavaScript Execution API (custom JS auf Seiten ausführen)

### Aktueller Roadmap-Status

Zuletzt abgeschlossen: Iris Paket 1 — Gerüst + Core Fetcher
Nächster Schritt: Iris Paket 2 — Advanced Features + Robustness
Datum: 2026-02-27
