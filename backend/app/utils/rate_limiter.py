"""
Simple in-process token-bucket rate limiter.

Used to throttle external API calls (Overpass, Nominatim, DuckDuckGo)
so we don't hammer free services and trigger bans.

Usage
-----
    limiter = RateLimiter(calls_per_second=1.0)
    async with limiter:
        response = await client.get(url)
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Deque

from app.utils.logger import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """
    Async-compatible sliding-window rate limiter.

    Parameters
    ----------
    calls_per_second:
        Maximum number of calls allowed per second (can be < 1 for
        sub-one-per-second rates, e.g. 0.5 = one call every 2 s).
    name:
        Friendly name used in log messages.
    """

    def __init__(self, calls_per_second: float = 1.0, name: str = "default") -> None:
        if calls_per_second <= 0:
            raise ValueError("calls_per_second must be positive")
        self._min_interval: float = 1.0 / calls_per_second
        self._name = name
        self._last_called: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a call slot is available and then reserve it."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_called
            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                logger.debug(
                    "rate_limiter_wait",
                    limiter=self._name,
                    wait_s=round(wait_time, 3),
                )
                await asyncio.sleep(wait_time)
            self._last_called = time.monotonic()

    async def __aenter__(self) -> "RateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        pass


class MultiRateLimiter:
    """
    Registry of named RateLimiter instances.

    Useful for sharing one limiter per external domain across all callers.
    """

    _limiters: dict[str, RateLimiter] = {}

    @classmethod
    def get(cls, name: str, calls_per_second: float = 1.0) -> RateLimiter:
        """Return (and lazily create) a named rate limiter."""
        if name not in cls._limiters:
            cls._limiters[name] = RateLimiter(calls_per_second=calls_per_second, name=name)
        return cls._limiters[name]
