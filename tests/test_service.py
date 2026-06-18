from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.models import OrderModificationRequest, OrderPreviewRequest
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
        if path == "/api/v1/price-limits":
            return {
                "data": {
                    "upperLimitPrice": "91000",
                    "lowerLimitPrice": "49000",
                    "currency": "KRW",
                },
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
        if path == "/api/v1/sellable-quantity":
            return {
                "data": {"sellableQuantity": "20"},
                "meta": {},
            }
        if path == "/api/v1/accounts":
            return {
                "data": [
                    {
                        "accountNo": "12345678901",
                        "accountSeq": 1,
                        "accountType": "BROKERAGE",
                    }
                ],
                "meta": {},
            }
        if method == "POST" and path == "/api/v1/orders":
            return {
                "data": {"orderId": "order-1", "clientOrderId": kwargs["json"]["clientOrderId"]},
                "meta": {},
            }
        if method == "POST" and path.endswith("/modify"):
            return {"data": {"orderId": "order-2"}, "meta": {}}
        if method == "POST" and path.endswith("/cancel"):
            return {"data": {"orderId": "order-3"}, "meta": {}}
        if path.startswith("/api/v1/orders/"):
            order_id = path.rsplit("/", 1)[-1]
            return {
                "data": {
                    "orderId": order_id,
                    "symbol": "005930",
                    "side": "BUY",
                    "orderType": "LIMIT",
                    "quantity": "10",
                    "price": "70000",
                    "currency": "KRW",
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


@pytest.mark.asyncio
async def test_account_identifiers_are_redacted(settings: Settings) -> None:
    service = TossInvestService(settings, StubClient())  # type: ignore[arg-type]

    response = await service.list_accounts()

    assert response["data"] == [{"account_type": "BROKERAGE", "selected": True}]
    assert "accountNo" not in str(response)
    assert "accountSeq" not in str(response)
    assert "12345678901" not in str(response)


@pytest.mark.asyncio
async def test_korean_amount_order_is_rejected(
    trading_settings: Settings,
) -> None:
    service = TossInvestService(trading_settings, StubClient())  # type: ignore[arg-type]

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order(
            OrderPreviewRequest(
                symbol="005930",
                side="BUY",
                order_type="MARKET",
                order_amount="1000",
            )
        )

    assert exc_info.value.code == "amount-order-market-not-supported"


@pytest.mark.asyncio
async def test_korean_market_order_uses_upper_limit_for_safety(
    trading_settings: Settings,
) -> None:
    trading_settings.tossinvest_max_order_krw = Decimal("80000")
    service = TossInvestService(trading_settings, StubClient())  # type: ignore[arg-type]

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order(
            OrderPreviewRequest(
                symbol="005930",
                side="BUY",
                order_type="MARKET",
                quantity="1",
            )
        )

    assert exc_info.value.code == "configured-order-limit-exceeded"
    assert exc_info.value.data == {"estimated": "91000", "limit": "80000"}


@pytest.mark.asyncio
async def test_preview_rejects_insufficient_buying_power(
    trading_settings: Settings,
) -> None:
    service = TossInvestService(trading_settings, StubClient())  # type: ignore[arg-type]

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order(
            OrderPreviewRequest(
                symbol="005930",
                side="BUY",
                order_type="LIMIT",
                quantity="100",
                price="70000",
            )
        )

    assert exc_info.value.code == "insufficient-buying-power-preview"


@pytest.mark.asyncio
async def test_preview_rejects_insufficient_sellable_quantity(
    trading_settings: Settings,
) -> None:
    service = TossInvestService(trading_settings, StubClient())  # type: ignore[arg-type]

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order(
            OrderPreviewRequest(
                symbol="005930",
                side="SELL",
                order_type="LIMIT",
                quantity="21",
                price="70000",
            )
        )

    assert exc_info.value.code == "insufficient-sellable-quantity-preview"


@pytest.mark.asyncio
async def test_modify_and_cancel_require_one_time_confirmations(
    trading_settings: Settings,
) -> None:
    client = StubClient()
    service = TossInvestService(trading_settings, client)  # type: ignore[arg-type]

    modify_preview = await service.preview_order_modification(
        OrderModificationRequest(
            order_id="order-original",
            order_type="LIMIT",
            quantity="5",
            price="71000",
        )
    )
    modify_result = await service.modify_order(
        modify_preview["preview_id"],
        modify_preview["confirmation_phrase"],
    )
    assert modify_result["operation"]["data"]["orderId"] == "order-2"
    assert modify_result["order"]["data"]["orderId"] == "order-2"

    cancel_preview = await service.preview_order_cancellation("order-original")
    cancel_result = await service.cancel_order(
        cancel_preview["preview_id"],
        cancel_preview["confirmation_phrase"],
    )
    assert cancel_result["operation"]["data"]["orderId"] == "order-3"
    assert cancel_result["order"]["data"]["orderId"] == "order-3"

    writes = [call for call in client.calls if call["method"] == "POST"]
    assert [call["path"] for call in writes] == [
        "/api/v1/orders/order-original/modify",
        "/api/v1/orders/order-original/cancel",
    ]


@pytest.mark.asyncio
async def test_korean_modification_requires_quantity(
    trading_settings: Settings,
) -> None:
    service = TossInvestService(trading_settings, StubClient())  # type: ignore[arg-type]

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order_modification(
            OrderModificationRequest(
                order_id="order-original",
                order_type="LIMIT",
                price="71000",
            )
        )

    assert exc_info.value.code == "kr-modify-quantity-required"
