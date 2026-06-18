from __future__ import annotations

import pytest

from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.logging_utils import sanitize_for_log
from tossinvest_mcp.previews import PreviewStore


def test_sensitive_values_are_masked() -> None:
    value = {
        "Authorization": "Bearer a-very-long-token",
        "client_secret": "super-secret-value",
        "X-Tossinvest-Account": "1234567890",
        "safe": {"symbol": "005930"},
    }

    sanitized = sanitize_for_log(value)

    assert "very-long-token" not in str(sanitized)
    assert "super-secret-value" not in str(sanitized)
    assert "1234567890" not in str(sanitized)
    assert sanitized["safe"]["symbol"] == "005930"


@pytest.mark.asyncio
async def test_preview_is_one_time_and_expires() -> None:
    now = 100.0
    store = PreviewStore(ttl_seconds=120, clock=lambda: now)
    preview = await store.create("cancel", {"order_id": "order-1"}, "CONFIRM")

    consumed = await store.consume(
        preview.preview_id,
        "CONFIRM",
        expected_kind="cancel",
    )
    assert consumed.payload["order_id"] == "order-1"

    with pytest.raises(TossInvestError, match=r"does not exist|already used"):
        await store.consume(
            preview.preview_id,
            "CONFIRM",
            expected_kind="cancel",
        )

    second = await store.create("cancel", {"order_id": "order-2"}, "CONFIRM")
    now = 221.0
    with pytest.raises(TossInvestError, match="expired"):
        await store.consume(second.preview_id, "CONFIRM", expected_kind="cancel")
