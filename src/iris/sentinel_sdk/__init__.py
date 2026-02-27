"""Sentinel SDK — mTLS + JWT client for Sentinel gateway."""

from iris.sentinel_sdk.client import SentinelClient
from iris.sentinel_sdk.exceptions import (
    SentinelAuthError,
    SentinelConnectionError,
    SentinelError,
    SentinelTimeoutError,
)

__all__ = [
    "SentinelAuthError",
    "SentinelClient",
    "SentinelConnectionError",
    "SentinelError",
    "SentinelTimeoutError",
]
