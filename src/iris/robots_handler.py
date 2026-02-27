"""robots.txt handler with Redis caching and urllib.robotparser."""

from __future__ import annotations

import urllib.robotparser
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx

from iris.logging import get_logger

if TYPE_CHECKING:
    import redis.asyncio as redis

logger = get_logger(__name__)


class RobotsHandler:
    """Check robots.txt rules with Redis-backed caching."""

    def __init__(
        self,
        user_agent: str,
        redis_client: redis.Redis | None = None,  # type: ignore[type-arg]
        cache_ttl: int = 86400,
        respect_robots: bool = True,
    ) -> None:
        self._user_agent = user_agent
        self._redis = redis_client
        self._cache_ttl = cache_ttl
        self._respect_robots = respect_robots
        self._memory_cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    async def can_fetch(self, url: str) -> bool:
        """Check if URL is allowed by robots.txt.

        Args:
            url: The URL to check.

        Returns:
            True if allowed, False if blocked.
        """
        if not self._respect_robots:
            return True

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        parser = await self._get_parser(origin)
        if parser is None:
            return True

        return bool(parser.can_fetch(self._user_agent, url))

    async def _get_parser(
        self, origin: str
    ) -> urllib.robotparser.RobotFileParser | None:
        """Get or fetch robots.txt parser for an origin."""
        # Check memory cache
        if origin in self._memory_cache:
            return self._memory_cache[origin]

        # Check Redis cache
        if self._redis:
            try:
                cached = await self._redis.get(f"iris:robots:{origin}")
                if cached is not None:
                    parser = urllib.robotparser.RobotFileParser()
                    parser.parse(str(cached).split("\n"))
                    self._memory_cache[origin] = parser
                    return parser
            except Exception:
                logger.debug("Redis robots cache read failed for %s", origin)

        # Fetch robots.txt
        robots_url = f"{origin}/robots.txt"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(robots_url)

            if resp.status_code != 200:
                # No robots.txt or error — allow everything
                parser = urllib.robotparser.RobotFileParser()
                parser.parse([""])
                self._memory_cache[origin] = parser
                return parser

            content = resp.text
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(content.split("\n"))
            self._memory_cache[origin] = parser

            # Store in Redis
            if self._redis:
                try:
                    await self._redis.setex(
                        f"iris:robots:{origin}", self._cache_ttl, content
                    )
                except Exception:
                    logger.debug("Redis robots cache write failed for %s", origin)

            return parser

        except Exception as e:
            logger.warning("Failed to fetch robots.txt for %s: %s", origin, e)
            # Graceful: allow on failure
            return None
