from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.models import OrderPreviewRequest
from tossinvest_mcp.service import TossInvestService
from tossinvest_mcp.settings import Settings


class StubClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": method, "path": path, **kwargs})
        if path == "/api/v1/stocks":
            return {
                "data": [
                    {
                        "symbol": "005930",
                        "name": "삼성전자",
                        "currency": "KRW",
                        "market": "KOSPI",
                    }
                ],
                "meta": {},
            }
        if path == "/api/v1/prices":
            return {
                "data": [{"symbol": "005930", "lastPrice": "70000", "currency": "KRW"}],
                "meta": {},
            }
        if path.endswith("/warnings"):
            return {"data": [], "meta": {}}
        if path == "/api/v1/market-calendar/KR":
            return {"data": {"isOpen": True}, "meta": {}}
        if path == "/api/v1/buying-power":
            return {
                "data": {"currency": "KRW", "cashBuyingPower": "5000000"},
                "meta": {},
            }
        if method == "POST" and path == "/api/v1/orders":
            return {
                "data": {"orderId": "order-1", "clientOrderId": kwargs["json"]["clientOrderId"]},
                "meta": {},
            }
        if path == "/api/v1/orders/order-1":
            return {
                "data": {
                    "orderId": "order-1",
                    "symbol": "005930",
                    "side": "BUY",
                    "status": "PENDING",
                },
                "meta": {},
            }
        raise AssertionError(f"Unexpected request: {method} {path}")

    async def aclose(self) -> None:
        return None

    async def is_ready(self) -> bool:
        return True


class FailingLookupClient(StubClient):
    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if path == "/api/v1/orders/order-1":
            raise TossInvestError("lookup failed", code="upstream-network-error")
        return await super().request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_order_requires_preview_and_exact_confirmation(
    trading_settings: Settings,
) -> None:
    client = StubClient()
    service = TossInvestService(trading_settings, client)  # type: ignore[arg-type]
    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="005930",
            side="BUY",
            order_type="LIMIT",
            quantity="10",
            price="70000",
        )
    )

    with pytest.raises(TossInvestError, match="does not match"):
        await service.place_order(preview["preview_id"], "WRONG")

    result = await service.place_order(
        preview["preview_id"],
        preview["confirmation_phrase"],
    )
    operation_payload = result["operation"]["data"]
    assert operation_payload["orderId"] == "order-1"
    assert len(operation_payload["clientOrderId"]) == 32
    assert result["order"]["data"]["status"] == "PENDING"

    with pytest.raises(TossInvestError, match=r"does not exist|already used"):
        await service.place_order(
            preview["preview_id"],
            preview["confirmation_phrase"],
        )


@pytest.mark.asyncio
async def test_configured_order_limit_is_enforced(
    trading_settings: Settings,
) -> None:
    trading_settings.tossinvest_max_order_krw = Decimal("100000")
    service = TossInvestService(trading_settings, StubClient())  # type: ignore[arg-type]

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order(
            OrderPreviewRequest(
                symbol="005930",
                side="BUY",
                order_type="LIMIT",
                quantity="10",
                price="70000",
            )
        )

    assert exc_info.value.code == "configured-order-limit-exceeded"


@pytest.mark.asyncio
async def test_successful_write_is_not_repeated_when_followup_lookup_fails(
    trading_settings: Settings,
) -> None:
    client = FailingLookupClient()
    service = TossInvestService(trading_settings, client)  # type: ignore[arg-type]
    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="005930",
            side="BUY",
            order_type="LIMIT",
            quantity="1",
            price="70000",
        )
    )

    result = await service.place_order(
        preview["preview_id"],
        preview["confirmation_phrase"],
    )

    assert result["operation"]["data"]["orderId"] == "order-1"
    assert result["order"] is None
    assert "Do not repeat" in result["warning"]
    assert sum(call["method"] == "POST" for call in client.calls) == 1
