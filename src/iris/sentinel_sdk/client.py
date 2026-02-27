"""Sentinel gateway client with mTLS + JWT authentication."""

from __future__ import annotations

import asyncio
import ssl
import time
from pathlib import Path
from typing import Any

import httpx
import jwt

from iris.logging import get_logger
from iris.sentinel_sdk.exceptions import (
    SentinelAuthError,
    SentinelConnectionError,
    SentinelError,
    SentinelTimeoutError,
)

log = get_logger("sentinel_sdk")

_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_JWT_EXPIRY_SECONDS = 300


class SentinelClient:
    """Client for communicating with Sentinel gateway via mTLS + JWT."""

    def __init__(
        self,
        sentinel_url: str,
        satellite_id: str,
        satellite_secret: str,
        cert_path: Path | None = None,
        key_path: Path | None = None,
        ca_path: Path | None = None,
        testing_mode: bool = False,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.sentinel_url = sentinel_url.rstrip("/")
        self.satellite_id = satellite_id
        self.satellite_secret = satellite_secret
        self.cert_path = cert_path
        self.key_path = key_path
        self.ca_path = ca_path
        self.testing_mode = testing_mode
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def connect(self) -> None:
        """Initialize the HTTP client with mTLS certificates."""
        if self._client is not None:
            return

        if self.testing_mode:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            )
            log.info("Sentinel client connected (testing mode)")
            return

        if not self.cert_path or not self.key_path or not self.ca_path:
            raise SentinelAuthError("Certificate paths required for production mode")

        if not self.cert_path.exists():
            raise SentinelAuthError(f"Certificate not found: {self.cert_path}")
        if not self.key_path.exists():
            raise SentinelAuthError(f"Key not found: {self.key_path}")
        if not self.ca_path.exists():
            raise SentinelAuthError(f"CA certificate not found: {self.ca_path}")

        ssl_context = ssl.create_default_context(cafile=str(self.ca_path))
        ssl_context.load_cert_chain(
            certfile=str(self.cert_path),
            keyfile=str(self.key_path),
        )

        self._client = httpx.AsyncClient(
            verify=ssl_context,
            timeout=self.timeout,
            follow_redirects=True,
        )
        log.info("Sentinel client connected (mTLS mode)")

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
            log.info("Sentinel client closed")

    def _generate_jwt(self) -> str:
        """Generate a JWT token for Sentinel authentication."""
        now = int(time.time())
        payload = {
            "sub": self.satellite_id,
            "iat": now,
            "exp": now + _JWT_EXPIRY_SECONDS,
        }
        return jwt.encode(payload, self.satellite_secret, algorithm="HS256")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Make an authenticated request to Sentinel with retry logic."""
        if self._client is None:
            raise SentinelConnectionError("Client not connected. Call connect() first.")

        url = f"{self.sentinel_url}{path}"
        request_headers = {
            "Authorization": f"Bearer {self._generate_jwt()}",
            "X-Satellite-ID": self.satellite_id,
            **(headers or {}),
        }

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = await self._client.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    headers=request_headers,
                    timeout=timeout or self.timeout,
                )

                if response.status_code == 401:
                    raise SentinelAuthError("Authentication failed")
                if response.status_code == 403:
                    raise SentinelAuthError("Authorization denied")

                response.raise_for_status()
                return response

            except (SentinelAuthError, SentinelError):
                raise
            except httpx.TimeoutException as e:
                last_error = SentinelTimeoutError(str(e))
            except httpx.ConnectError as e:
                last_error = SentinelConnectionError(str(e))
            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    last_error = SentinelError(
                        f"Server error {e.response.status_code}: {e.response.text}"
                    )
                else:
                    raise SentinelError(
                        f"HTTP {e.response.status_code}: {e.response.text}"
                    ) from e
            except httpx.HTTPError as e:
                last_error = SentinelError(str(e))

            if attempt < _MAX_RETRIES - 1:
                backoff = _BACKOFF_BASE * (2**attempt)
                log.warning(
                    "Sentinel retry: attempt=%d backoff=%.1fs error=%s",
                    attempt + 1,
                    backoff,
                    str(last_error),
                )
                await asyncio.sleep(backoff)

        raise last_error or SentinelError("Request failed after retries")

    async def request(
        self,
        target: str,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send a request through Sentinel's routing endpoint."""
        response = await self._request(
            "POST",
            "/request",
            json={
                "target": target,
                "action": action,
                "payload": payload or {},
            },
            timeout=timeout,
        )
        return response.json()  # type: ignore[no-any-return]

    async def request_stream(
        self,
        target: str,
        action: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> httpx.Response:
        """Send a streaming request through Sentinel (for SSE)."""
        if self._client is None:
            raise SentinelConnectionError("Client not connected. Call connect() first.")

        url = f"{self.sentinel_url}/request"
        request_headers = {
            "Authorization": f"Bearer {self._generate_jwt()}",
            "X-Satellite-ID": self.satellite_id,
            "Accept": "text/event-stream",
        }

        response = await self._client.request(
            "POST",
            url,
            json={
                "target": target,
                "action": action,
                "payload": payload or {},
                "stream": True,
            },
            headers=request_headers,
            timeout=timeout or self.timeout,
        )

        if response.status_code == 401:
            raise SentinelAuthError("Authentication failed")
        if response.status_code == 403:
            raise SentinelAuthError("Authorization denied")

        response.raise_for_status()
        return response

    async def health(self) -> dict[str, Any]:
        """Check Sentinel health."""
        response = await self._request("GET", "/health")
        return response.json()  # type: ignore[no-any-return]

    async def whoami(self) -> dict[str, Any]:
        """Get current satellite identity."""
        response = await self._request("GET", "/whoami")
        return response.json()  # type: ignore[no-any-return]
