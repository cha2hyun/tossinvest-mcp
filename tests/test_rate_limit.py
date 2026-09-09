from __future__ import annotations

import pytest

from tossinvest_mcp.rate_limit import ApprovalAttemptLimiter


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
