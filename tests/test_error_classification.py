"""Tests for error classification — all FetchErrorType variants."""

from __future__ import annotations

from iris.fetcher import classify_error, classify_http_error
from iris.schemas import FetchError, FetchErrorType


class TestClassifyError:
    """Tests for exception-to-FetchError classification."""

    def test_timeout_error(self) -> None:
        """Should classify TimeoutError as TIMEOUT."""
        error = classify_error(TimeoutError("Navigation timeout"))
        assert error.type == FetchErrorType.TIMEOUT
        assert error.retryable is True

    def test_timeout_in_message(self) -> None:
        """Should classify errors with 'timeout' in message."""
        error = classify_error(Exception("page timeout after 30s"))
        assert error.type == FetchErrorType.TIMEOUT
        assert error.retryable is True

    def test_dns_error(self) -> None:
        """Should classify DNS errors."""
        error = classify_error(Exception("DNS resolution failed"))
        assert error.type == FetchErrorType.DNS_ERROR
        assert error.retryable is True

    def test_dns_getaddrinfo(self) -> None:
        """Should classify getaddrinfo errors as DNS."""
        error = classify_error(OSError("getaddrinfo failed"))
        assert error.type == FetchErrorType.DNS_ERROR
        assert error.retryable is True

    def test_name_resolution_error(self) -> None:
        """Should classify name resolution errors."""
        error = classify_error(Exception("Name resolution failed"))
        assert error.type == FetchErrorType.DNS_ERROR
        assert error.retryable is True

    def test_ssl_error(self) -> None:
        """Should classify SSL errors."""
        error = classify_error(Exception("SSL certificate verify failed"))
        assert error.type == FetchErrorType.SSL_ERROR
        assert error.retryable is False

    def test_connection_error(self) -> None:
        """Should classify ConnectionError."""
        error = classify_error(ConnectionError("Connection refused"))
        assert error.type == FetchErrorType.CONNECTION_ERROR
        assert error.retryable is True

    def test_connection_reset(self) -> None:
        """Should classify connection reset."""
        error = classify_error(Exception("Connection reset by peer"))
        assert error.type == FetchErrorType.CONNECTION_ERROR
        assert error.retryable is True

    def test_connection_refused(self) -> None:
        """Should classify connection refused."""
        error = classify_error(Exception("Connection refused"))
        assert error.type == FetchErrorType.CONNECTION_ERROR
        assert error.retryable is True

    def test_browser_error_default(self) -> None:
        """Should default to BROWSER_ERROR for unknown errors."""
        error = classify_error(RuntimeError("Something unknown happened"))
        assert error.type == FetchErrorType.BROWSER_ERROR
        assert error.retryable is False

    def test_error_message_preserved(self) -> None:
        """Should preserve the original error message."""
        error = classify_error(ValueError("test message"))
        assert "test message" in error.message
        assert "ValueError" in error.message


class TestClassifyHttpError:
    """Tests for HTTP status code classification."""

    def test_429_rate_limited(self) -> None:
        """Should classify 429 as RATE_LIMITED."""
        error = classify_http_error(429)
        assert error.type == FetchErrorType.RATE_LIMITED
        assert error.retryable is True
        assert error.http_status == 429

    def test_502_retryable(self) -> None:
        """Should classify 502 as retryable HTTP_ERROR."""
        error = classify_http_error(502)
        assert error.type == FetchErrorType.HTTP_ERROR
        assert error.retryable is True
        assert error.http_status == 502

    def test_503_retryable(self) -> None:
        """Should classify 503 as retryable."""
        error = classify_http_error(503)
        assert error.retryable is True

    def test_504_retryable(self) -> None:
        """Should classify 504 as retryable."""
        error = classify_http_error(504)
        assert error.retryable is True

    def test_404_not_retryable(self) -> None:
        """Should classify 404 as NOT retryable."""
        error = classify_http_error(404)
        assert error.type == FetchErrorType.HTTP_ERROR
        assert error.retryable is False
        assert error.http_status == 404

    def test_403_not_retryable(self) -> None:
        """Should classify 403 as NOT retryable."""
        error = classify_http_error(403)
        assert error.retryable is False

    def test_401_not_retryable(self) -> None:
        """Should classify 401 as NOT retryable."""
        error = classify_http_error(401)
        assert error.retryable is False

    def test_500_not_retryable(self) -> None:
        """Should classify 500 as NOT retryable (not in retryable set)."""
        error = classify_http_error(500)
        assert error.retryable is False


class TestFetchErrorModel:
    """Tests for FetchError model structure."""

    def test_error_with_all_fields(self) -> None:
        """Should create a complete FetchError."""
        error = FetchError(
            type=FetchErrorType.TIMEOUT,
            message="Timed out after 30s",
            retryable=True,
            http_status=None,
        )
        assert error.type == FetchErrorType.TIMEOUT
        assert error.retryable is True
        assert error.http_status is None

    def test_error_with_http_status(self) -> None:
        """Should include HTTP status when relevant."""
        error = FetchError(
            type=FetchErrorType.HTTP_ERROR,
            message="HTTP 502",
            retryable=True,
            http_status=502,
        )
        assert error.http_status == 502

    def test_all_error_types_exist(self) -> None:
        """All documented error types should exist in the enum."""
        expected = [
            "timeout",
            "dns_error",
            "connection_error",
            "ssl_error",
            "blocked_by_robots_txt",
            "rate_limited",
            "unsupported_content_type",
            "invalid_url",
            "http_error",
            "content_too_large",
            "browser_error",
        ]
        actual = [e.value for e in FetchErrorType]
        for name in expected:
            assert name in actual, f"Missing error type: {name}"
