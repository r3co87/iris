"""Iris configuration via Pydantic Settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="IRIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Service
    HOST: str = "0.0.0.0"
    PORT: int = 8060
    LOG_LEVEL: str = "INFO"

    # Playwright
    BROWSER_TYPE: str = "chromium"
    HEADLESS: bool = True
    PAGE_TIMEOUT_MS: int = 30000
    WAIT_AFTER_LOAD_MS: int = 2000
    MAX_CONCURRENT_PAGES: int = 3
    USER_AGENT: str = "Cortex-Iris/1.0 (Research Bot)"

    # Content Extraction
    MAX_CONTENT_LENGTH: int = 500000
    EXTRACT_METADATA: bool = True
    EXTRACT_LINKS: bool = True

    # Cache (Redis)
    REDIS_URL: str = "redis://redis:6379/4"
    CACHE_TTL_SECONDS: int = 3600
    CACHE_ENABLED: bool = True

    # Rate Limiting (Politeness)
    MIN_DELAY_BETWEEN_REQUESTS_MS: int = 1000
    RESPECT_ROBOTS_TXT: bool = True

    # Sentinel
    TESTING_MODE: bool = False
    SENTINEL_URL: str = "https://sentinel:8443"
    SATELLITE_ID: str = "satellite-iris"
    SATELLITE_SECRET: str = ""
    SENTINEL_CERT_PATH: Path = Path("/run/secrets/iris_cert")
    SENTINEL_KEY_PATH: Path = Path("/run/secrets/iris_key")
    SENTINEL_CA_PATH: Path = Path("/run/secrets/ca_cert")

    def load_secret(self, secret_path: Path) -> str:
        """Load a Docker secret from file."""
        if secret_path.exists():
            return secret_path.read_text().strip()
        return ""

    def get_satellite_secret(self) -> str:
        """Get satellite secret from env or Docker secret."""
        if self.SATELLITE_SECRET:
            return self.SATELLITE_SECRET
        secret = Path("/run/secrets/iris_satellite_secret")
        return self.load_secret(secret)


def get_settings() -> Settings:
    """Create settings instance."""
    return Settings()
