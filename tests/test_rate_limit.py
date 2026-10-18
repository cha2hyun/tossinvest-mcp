from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import tossinvest_mcp.rate_limit as rate_limit_module
from tossinvest_mcp.rate_limit import ApprovalAttemptLimiter, RateLimiter


@pytest.mark.asyncio
async def test_sector_and_ranking_limits_are_independent_five_request_buckets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    waits: list[float] = []

    async def sleep(delay: float) -> None:
        nonlocal now
        waits.append(delay)
        now += delay

    monkeypatch.setattr(rate_limit_module, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(
        rate_limit_module,
        "asyncio",
        SimpleNamespace(Lock=asyncio.Lock, sleep=sleep),
    )
    limiter = RateLimiter()
    for group in ("SECTOR", "SECTOR_RANKING"):
        for _ in range(5):
            await limiter.acquire(group)
    assert waits == []

    await limiter.acquire("SECTOR")
    assert waits == pytest.approx([0.2])


@pytest.mark.asyncio
async def test_approval_attempts_expire_without_retaining_inactive_clients() -> None:
    now = 0.0
    limiter = ApprovalAttemptLimiter(limit=2, window_seconds=60, clock=lambda: now)
    assert await limiter.allow("alpha")
    assert await limiter.allow("alpha")
    assert not await limiter.allow("alpha")
    now = 30.0
    assert await limiter.allow("beta")
    now = 60.0
    assert await limiter.allow("alpha")
    assert set(limiter._attempts) == {"alpha", "beta"}
    now = 120.0
    assert await limiter.allow("gamma")
    assert set(limiter._attempts) == {"gamma"}
