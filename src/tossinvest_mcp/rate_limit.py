from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

RATE_LIMITS: dict[str, float] = {
    "AUTH": 5,
    "ACCOUNT": 1,
    "ASSET": 5,
    "STOCK": 5,
    "MARKET_INFO": 3,
    "MARKET_DATA": 10,
    "MARKET_DATA_CHART": 5,
    "ORDER": 3,
    "ORDER_HISTORY": 5,
    "ORDER_INFO": 3,
}


@dataclass
class _Bucket:
    capacity: float
    tokens: float
    updated_at: float
    lock: asyncio.Lock


class RateLimiter:
    """Per-process token buckets keyed by the official Toss API rate-limit groups."""

    def __init__(self, limits: dict[str, float] | None = None) -> None:
        now = time.monotonic()
        self._buckets = {
            name: _Bucket(limit, limit, now, asyncio.Lock())
            for name, limit in (limits or RATE_LIMITS).items()
        }

    async def acquire(self, group: str) -> None:
        bucket = self._buckets[group]
        while True:
            async with bucket.lock:
                now = time.monotonic()
                elapsed = now - bucket.updated_at
                bucket.tokens = min(bucket.capacity, bucket.tokens + elapsed * bucket.capacity)
                bucket.updated_at = now
                if bucket.tokens >= 1:
                    bucket.tokens -= 1
                    return
                delay = (1 - bucket.tokens) / bucket.capacity
            await asyncio.sleep(delay)
