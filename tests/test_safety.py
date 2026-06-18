from __future__ import annotations

import pytest

from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.logging_utils import sanitize_for_log
from tossinvest_mcp.previews import PreviewStore


def test_sensitive_values_are_masked() -> None:
    value = {
        "Authorization": "Bearer a-very-long-token",
        "client_secret": "super-secret-value",
        "approval_token": "human-approval-token-value",
        "tossinvest_approval_token_sha256": "a" * 64,
        "X-Tossinvest-Account": "1234567890",
        "safe": {"symbol": "005930"},
    }

    sanitized = sanitize_for_log(value)

    assert "very-long-token" not in str(sanitized)
    assert "super-secret-value" not in str(sanitized)
    assert "human-approval-token-value" not in str(sanitized)
    assert "a" * 64 not in str(sanitized)
    assert "1234567890" not in str(sanitized)
    assert sanitized["safe"]["symbol"] == "005930"


@pytest.mark.asyncio
async def test_preview_is_one_time_and_expires() -> None:
    now = 100.0
    store = PreviewStore(ttl_seconds=120, clock=lambda: now)
    preview = await store.create(
        "cancel",
        {"order_id": "order-1"},
        {"operation": "cancel"},
    )

    with pytest.raises(TossInvestError) as exc_info:
        await store.consume(preview.preview_id, expected_kind="cancel")
    assert exc_info.value.code == "approval-required"

    await store.approve(preview.preview_id)
    consumed = await store.consume(preview.preview_id, expected_kind="cancel")
    assert consumed.payload["order_id"] == "order-1"
    assert consumed.approved is True

    with pytest.raises(TossInvestError, match=r"does not exist|already used"):
        await store.consume(preview.preview_id, expected_kind="cancel")

    second = await store.create(
        "cancel",
        {"order_id": "order-2"},
        {"operation": "cancel"},
    )
    now = 221.0
    with pytest.raises(TossInvestError, match="expired"):
        await store.approve(second.preview_id)


@pytest.mark.asyncio
async def test_preview_is_invalidated_after_repeated_approval_failures() -> None:
    store = PreviewStore()
    preview = await store.create(
        "create",
        {"symbol": "005930"},
        {"operation": "create"},
    )

    for _ in range(5):
        await store.record_approval_failure(preview.preview_id)

    with pytest.raises(TossInvestError) as exc_info:
        await store.get(preview.preview_id)
    assert exc_info.value.code == "preview-not-found"
