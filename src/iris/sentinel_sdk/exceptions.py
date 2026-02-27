"""Sentinel SDK exceptions."""


class SentinelError(Exception):
    """Base exception for Sentinel SDK."""


class SentinelAuthError(SentinelError):
    """Authentication or authorization failure."""


class SentinelConnectionError(SentinelError):
    """Cannot connect to Sentinel."""


class SentinelTimeoutError(SentinelError):
    """Request to Sentinel timed out."""
