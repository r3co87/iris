"""Tests for DomainRateLimiter — Token Bucket per domain."""

from __future__ import annotations

import time

import fakeredis.aioredis
import pytest

from iris.rate_limiter import DomainRateLimiter


@pytest.fixture
def fake_redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def limiter_memory() -> DomainRateLimiter:
    """Rate limiter without Redis (memory fallback)."""
    return DomainRateLimiter(redis_client=None, min_delay_ms=100, burst=2)


@pytest.fixture
def limiter_redis(fake_redis: fakeredis.aioredis.FakeRedis) -> DomainRateLimiter:
    """Rate limiter with Redis."""
    return DomainRateLimiter(redis_client=fake_redis, min_delay_ms=100, burst=2)


class TestDomainRateLimiterMemory:
    """Tests for in-memory rate limiting fallback."""

    @pytest.mark.asyncio
    async def test_first_request_immediate(
        self, limiter_memory: DomainRateLimiter
    ) -> None:
        """First request should be immediate."""
        start = time.monotonic()
        result = await limiter_memory.acquire("example.com")
        elapsed = time.monotonic() - start
        assert result is True
        assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_rate_limit_enforced(self, limiter_memory: DomainRateLimiter) -> None:
        """Second request to same domain should be delayed."""
        await limiter_memory.acquire("example.com")
        start = time.monotonic()
        await limiter_memory.acquire("example.com")
        elapsed = time.monotonic() - start
        assert elapsed >= 0.08  # 100ms min delay with tolerance

    @pytest.mark.asyncio
    async def test_different_domains_independent(
        self, limiter_memory: DomainRateLimiter
    ) -> None:
        """Different domains should not block each other."""
        await limiter_memory.acquire("domain1.com")
        start = time.monotonic()
        await limiter_memory.acquire("domain2.com")
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    @pytest.mark.asyncio
    async def test_rate_property(self, limiter_memory: DomainRateLimiter) -> None:
        """Rate property should compute correctly."""
        assert limiter_memory.rate == 10.0  # 1000/100 = 10 req/s


class TestDomainRateLimiterRedis:
    """Tests for Redis-backed rate limiting."""

    @pytest.mark.asyncio
    async def test_acquire_success(self, limiter_redis: DomainRateLimiter) -> None:
        """Should acquire token from Redis."""
        result = await limiter_redis.acquire("example.com")
        assert result is True

    @pytest.mark.asyncio
    async def test_burst_allows_multiple(
        self, limiter_redis: DomainRateLimiter
    ) -> None:
        """Burst should allow multiple immediate requests."""
        start = time.monotonic()
        # Burst of 2 should allow 2 immediate requests
        await limiter_redis.acquire("burst-test.com")
        await limiter_redis.acquire("burst-test.com")
        elapsed = time.monotonic() - start
        # Both should be fast (burst allowance)
        assert elapsed < 0.5

    @pytest.mark.asyncio
    async def test_redis_fallback_on_error(self) -> None:
        """Should fall back to memory when Redis errors."""
        # Create a broken Redis client
        broken_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
        await broken_redis.close()

        limiter = DomainRateLimiter(redis_client=broken_redis, min_delay_ms=50, burst=2)
        # Should still work via memory fallback
        result = await limiter.acquire("example.com")
        assert result is True
