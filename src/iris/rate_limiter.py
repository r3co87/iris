"""Redis-based Token Bucket rate limiter per domain."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from iris.logging import get_logger

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = get_logger(__name__)

# Lua script for atomic token bucket check-and-consume
_TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local burst = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens = burst
    last_refill = now
end

-- Refill tokens
local elapsed = now - last_refill
local new_tokens = elapsed * rate
tokens = math.min(burst, tokens + new_tokens)

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return 1
else
    -- Return time until next token is available
    local wait = (1 - tokens) / rate
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 3600)
    return -wait * 1000
end
"""


class DomainRateLimiter:
    """Per-domain rate limiter using Token Bucket algorithm in Redis."""

    def __init__(
        self,
        redis_client: redis.Redis | None = None,  # type: ignore[type-arg]
        min_delay_ms: int = 1000,
        burst: int = 3,
    ) -> None:
        self._redis = redis_client
        self._min_delay_ms = min_delay_ms
        self._burst = burst
        self._script_sha: str | None = None
        # Fallback in-memory state when Redis is unavailable
        self._memory_last: dict[str, float] = {}
        self._memory_locks: dict[str, asyncio.Lock] = {}

    @property
    def rate(self) -> float:
        """Requests per second."""
        return 1000.0 / self._min_delay_ms if self._min_delay_ms > 0 else 100.0

    async def acquire(self, domain: str) -> bool:
        """Acquire a rate limit token for a domain. Waits if necessary.

        Args:
            domain: The domain to rate-limit.

        Returns:
            True when the token is acquired.
        """
        if self._redis:
            return await self._acquire_redis(domain)
        return await self._acquire_memory(domain)

    async def _acquire_redis(self, domain: str) -> bool:
        """Acquire token using Redis-backed token bucket."""
        assert self._redis is not None
        key = f"iris:ratelimit:{domain}"

        try:
            if self._script_sha is None:
                self._script_sha = await self._redis.script_load(  # type: ignore[no-untyped-call]
                    _TOKEN_BUCKET_SCRIPT
                )

            now = time.monotonic()
            result = await self._redis.evalsha(  # type: ignore[no-untyped-call]
                self._script_sha, 1, key, str(now), str(self.rate), str(self._burst)
            )
            result_num = float(str(result))

            if result_num == 1:
                return True

            # result_num is negative wait time in ms
            wait_ms = abs(result_num)
            logger.info("Rate limiting domain=%s wait=%.0fms", domain, wait_ms)
            await asyncio.sleep(wait_ms / 1000.0)
            # Retry after waiting
            return await self._acquire_redis(domain)

        except Exception:
            logger.debug("Redis rate limit failed, falling back to memory")
            return await self._acquire_memory(domain)

    async def _acquire_memory(self, domain: str) -> bool:
        """Fallback in-memory rate limiting."""
        if domain not in self._memory_locks:
            self._memory_locks[domain] = asyncio.Lock()

        lock = self._memory_locks[domain]
        async with lock:
            now = time.monotonic()
            last = self._memory_last.get(domain, 0.0)
            min_delay = self._min_delay_ms / 1000.0
            elapsed = now - last

            if elapsed < min_delay:
                wait_time = min_delay - elapsed
                logger.info("Rate limiting: domain=%s wait=%.2fs", domain, wait_time)
                await asyncio.sleep(wait_time)

            self._memory_last[domain] = time.monotonic()
            return True
