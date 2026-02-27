"""Tests for configuration module."""

from __future__ import annotations

from iris.config import Settings, get_settings


class TestSettings:
    """Tests for Settings configuration."""

    def test_defaults(self) -> None:
        """Should have correct default values."""
        settings = Settings(TESTING_MODE=True)
        assert settings.PORT == 8060
        assert settings.HOST == "0.0.0.0"
        assert settings.BROWSER_TYPE == "chromium"
        assert settings.HEADLESS is True
        assert settings.PAGE_TIMEOUT_MS == 30000
        assert settings.MAX_CONCURRENT_PAGES == 3
        assert settings.CACHE_TTL_SECONDS == 3600
        assert settings.CACHE_ENABLED is True
        assert settings.RESPECT_ROBOTS_TXT is True
        assert settings.MAX_CONTENT_LENGTH == 500000

    def test_custom_values(self) -> None:
        """Should accept custom values."""
        settings = Settings(
            PORT=9090,
            HEADLESS=False,
            MAX_CONCURRENT_PAGES=5,
            CACHE_ENABLED=False,
            TESTING_MODE=True,
        )
        assert settings.PORT == 9090
        assert settings.HEADLESS is False
        assert settings.MAX_CONCURRENT_PAGES == 5
        assert settings.CACHE_ENABLED is False

    def test_sentinel_defaults(self) -> None:
        """Should have correct Sentinel defaults."""
        settings = Settings(TESTING_MODE=True)
        assert settings.SENTINEL_URL == "https://sentinel:8443"
        assert settings.SATELLITE_ID == "satellite-iris"

    def test_get_satellite_secret_empty(self) -> None:
        """Should return empty string when no secret configured."""
        settings = Settings(TESTING_MODE=True)
        secret = settings.get_satellite_secret()
        assert isinstance(secret, str)

    def test_get_satellite_secret_from_env(self) -> None:
        """Should return secret from env var."""
        settings = Settings(TESTING_MODE=True, SATELLITE_SECRET="test-secret")
        assert settings.get_satellite_secret() == "test-secret"

    def test_get_settings_factory(self) -> None:
        """Should create settings via factory function."""
        settings = get_settings()
        assert isinstance(settings, Settings)

    def test_redis_url_default(self) -> None:
        """Should use DB 4 for Iris by default."""
        settings = Settings(TESTING_MODE=True)
        assert "6379/4" in settings.REDIS_URL
