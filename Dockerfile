FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# System dependencies for Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder

COPY pyproject.toml .
RUN pip install --no-cache-dir . && \
    playwright install chromium && \
    playwright install-deps chromium

COPY src/ src/

FROM base AS runtime

# Copy installed packages and playwright browsers
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# Copy Playwright system dependencies
COPY --from=builder /usr/lib/ /usr/lib/
COPY --from=builder /lib/ /lib/

COPY src/ src/

RUN useradd -r -s /bin/false iris

EXPOSE 8060

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD ["python", "-m", "iris.healthcheck"]

CMD ["python", "-m", "uvicorn", "iris.main:app", "--host", "0.0.0.0", "--port", "8060"]
