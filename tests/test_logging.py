"""Tests for logging module."""

from __future__ import annotations

import json
import logging

from iris.logging import JSONFormatter, get_logger, setup_logging


class TestJSONFormatter:
    """Tests for the JSON log formatter."""

    def test_format_basic_message(self) -> None:
        """Should format a log record as JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "Test message"
        assert data["level"] == "info"
        assert data["logger"] == "test"
        assert "timestamp" in data

    def test_format_with_exception(self) -> None:
        """Should include error info when exception is present."""
        formatter = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="Error occurred",
            args=None,
            exc_info=exc_info,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["error"] == "test error"
        assert data["error_type"] == "ValueError"

    def test_format_warning_level(self) -> None:
        """Should correctly format warning level."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=1,
            msg="Warning msg",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "warning"


class TestSetupLogging:
    """Tests for logging setup."""

    def test_setup_logging_default(self) -> None:
        """Should configure root logger with JSON formatter."""
        setup_logging("INFO")
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_setup_logging_debug(self) -> None:
        """Should set debug level."""
        setup_logging("DEBUG")
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_get_logger(self) -> None:
        """Should return a named logger."""
        logger = get_logger("test.module")
        assert logger.name == "test.module"
        assert isinstance(logger, logging.Logger)
