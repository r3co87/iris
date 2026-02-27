"""Docker healthcheck script for Iris."""

from __future__ import annotations

import sys

import httpx


def main() -> None:
    """Check if the service is healthy."""
    try:
        r = httpx.get("http://localhost:8060/health", timeout=5)
        if r.status_code == 200:
            sys.exit(0)
        sys.exit(1)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
