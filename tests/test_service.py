from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from tossinvest_mcp.errors import OrderStateUnknownError, TossInvestError
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


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": method, "path": path, **kwargs})
        return {"data": [], "meta": {}}

    async def aclose(self) -> None:
        return None

    async def is_ready(self) -> bool:
        return True


class FailingLookupClient(StubClient):
    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if path == "/api/v1/orders/order-1":
            raise TossInvestError("lookup failed", code="upstream-network-error")
        return await super().request(method, path, **kwargs)


class MalformedOperationClient(StubClient):
    def __init__(self, result: Any) -> None:
        super().__init__()
        self.result = result

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = await super().request(method, path, **kwargs)
        return {"data": self.result, "meta": {}} if method == "POST" else response


class DroppingBuyingPowerClient(StubClient):
    def __init__(self) -> None:
        super().__init__()
        self.buying_power_calls = 0

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        result = await super().request(method, path, **kwargs)
        if path == "/api/v1/buying-power":
            self.buying_power_calls += 1
            if self.buying_power_calls >= 2:
                result["data"]["cashBuyingPower"] = "100"
        return result


class UsStockClient(StubClient):
    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if path == "/api/v1/stocks":
            self.calls.append({"method": method, "path": path, **kwargs})
            return {
                "data": [
                    {
                        "symbol": "AAPL",
                        "name": "Apple",
                        "currency": "USD",
                        "market": "NASDAQ",
                    }
                ],
                "meta": {},
            }
        if path == "/api/v1/prices":
            self.calls.append({"method": method, "path": path, **kwargs})
            return {
                "data": [{"symbol": "AAPL", "lastPrice": "200", "currency": "USD"}],
                "meta": {},
            }
        return await super().request(method, path, **kwargs)


@pytest.mark.asyncio
async def test_new_openapi_read_operations_route_to_expected_groups(
    settings: Settings,
) -> None:
    client = RecordingClient()
    service = TossInvestService(settings, client)

    await service.list_stocks("KOSPI", security_type="STOCK", common_share=True)
    await service.get_stock_investor_trading("005930", 5, "2026-08-14")
    await service.get_stock_program_trades("005930")
    await service.get_stock_short_selling("005930")
    await service.get_stock_credit_trades("005930")
    await service.get_stock_securities_lending("005930")
    await service.get_rankings("TOP_GAINERS", "KR", "1d", True, 20)
    await service.get_market_indicator_prices("KOSPI,KR_BOND_3Y")
    await service.get_market_indicator_candles("KOSPI", "1d", 20, "2026-08-17T00:00:00Z")
    await service.get_market_indicator_investor_trading("KOSPI", "1w", 5, "2026-08-14")
    await service.list_conditional_orders("OPEN", "005930", "next_cursor", 10)
    await service.get_conditional_order("conditional-1")

    assert [(call["path"], call["group"]) for call in client.calls] == [
        ("/api/v1/stocks/all", "STOCK_ALL"),
        ("/api/v1/stocks/005930/investor-trading", "STOCK_TRADING_TREND"),
        ("/api/v1/stocks/005930/program-trades", "STOCK_TRADING_TREND"),
        ("/api/v1/stocks/005930/short-selling", "STOCK_TRADING_TREND"),
        ("/api/v1/stocks/005930/credit-trades", "STOCK_TRADING_TREND"),
        ("/api/v1/stocks/005930/securities-lending", "STOCK_TRADING_TREND"),
        ("/api/v1/rankings", "RANKING"),
        ("/api/v1/market-indicators/prices", "MARKET_INDICATOR"),
        ("/api/v1/market-indicators/KOSPI/candles", "MARKET_INDICATOR_CHART"),
        ("/api/v1/market-indicators/KOSPI/investor-trading", "MARKET_INDICATOR"),
        ("/api/v1/conditional-orders", "CONDITIONAL_ORDER_HISTORY"),
        ("/api/v1/conditional-orders/conditional-1", "CONDITIONAL_ORDER_HISTORY"),
    ]
    assert client.calls[0]["params"] == {
        "market": "KOSPI",
        "status": "ACTIVE",
        "securityType": "STOCK",
        "commonShare": True,
    }
    assert client.calls[1]["params"] == {"count": 5, "until": "2026-08-14"}
    assert client.calls[6]["params"] == {
        "type": "TOP_GAINERS",
        "marketCountry": "KR",
        "duration": "1d",
        "excludeInvestmentCaution": True,
        "count": 20,
    }
    assert client.calls[10]["account_required"] is True
    assert client.calls[11]["account_required"] is True


@pytest.mark.asyncio
async def test_order_requires_separate_human_approval(
    trading_settings: Settings,
) -> None:
    client = StubClient()
    service = TossInvestService(trading_settings, client)
    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="005930",
            side="BUY",
            order_type="LIMIT",
            quantity="10",
            price="70000",
        )
    )

    assert "confirmation_phrase" not in preview
    assert preview["status"] == "pending_human_approval"
    assert preview["approval_url"].endswith(f"/approvals/{preview['preview_id']}")

    with pytest.raises(TossInvestError) as exc_info:
        await service.place_order(preview["preview_id"])
    assert exc_info.value.code == "approval-required"
    assert not any(call["method"] == "POST" for call in client.calls)

    await service.approve_preview(preview["preview_id"])
    result = await service.place_order(preview["preview_id"])
    operation_payload = result["operation"]["data"]
    assert operation_payload["orderId"] == "order-1"
    assert len(operation_payload["clientOrderId"]) == 32
    assert result["order"]["data"]["status"] == "PENDING"

    with pytest.raises(TossInvestError, match=r"does not exist|already used"):
        await service.place_order(preview["preview_id"])


@pytest.mark.asyncio
async def test_configured_order_limit_is_enforced(
    trading_settings: Settings,
) -> None:
    trading_settings.tossinvest_max_order_krw = Decimal("100000")
    service = TossInvestService(trading_settings, StubClient())

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
async def test_approved_order_is_revalidated_before_dispatch(
    trading_settings: Settings,
) -> None:
    client = DroppingBuyingPowerClient()
    service = TossInvestService(trading_settings, client)
    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="005930",
            side="BUY",
            order_type="LIMIT",
            quantity="1",
            price="70000",
        )
    )
    await service.approve_preview(preview["preview_id"])

    with pytest.raises(TossInvestError) as exc_info:
        await service.place_order(preview["preview_id"])

    assert exc_info.value.code == "preview-state-changed"
    assert not any(call["method"] == "POST" for call in client.calls)
    with pytest.raises(TossInvestError) as reused:
        await service.place_order(preview["preview_id"])
    assert reused.value.code == "preview-not-found"


@pytest.mark.asyncio
async def test_us_quantity_market_order_is_rejected_as_unbounded(
    trading_settings: Settings,
) -> None:
    service = TossInvestService(trading_settings, UsStockClient())

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order(
            OrderPreviewRequest(
                symbol="AAPL",
                side="BUY",
                order_type="MARKET",
                quantity="1",
            )
        )

    assert exc_info.value.code == "unbounded-market-order"


@pytest.mark.asyncio
async def test_successful_write_is_not_repeated_when_followup_lookup_fails(
    trading_settings: Settings,
) -> None:
    client = FailingLookupClient()
    service = TossInvestService(trading_settings, client)
    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="005930",
            side="BUY",
            order_type="LIMIT",
            quantity="1",
            price="70000",
        )
    )

    await service.approve_preview(preview["preview_id"])
    result = await service.place_order(preview["preview_id"])

    assert result["operation"]["data"]["orderId"] == "order-1"
    assert result["order"] is None
    assert "Do not repeat" in result["warning"]
    assert sum(call["method"] == "POST" for call in client.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["create", "modify", "cancel"])
@pytest.mark.parametrize("data", [None, [], {}, {"orderId": 42}, {"orderId": " "}])
async def test_unverifiable_write_response_consumes_preview_and_reports_unknown_state(
    trading_settings: Settings, kind: str, data: Any
) -> None:
    client = MalformedOperationClient(data)
    service = TossInvestService(trading_settings, client)
    if kind == "create":
        preview = await service.preview_order(
            OrderPreviewRequest(
                symbol="005930", side="BUY", order_type="LIMIT", quantity="1", price="70000"
            )
        )
        execute = service.place_order
    elif kind == "modify":
        preview = await service.preview_order_modification(
            OrderModificationRequest(
                order_id="order-1", order_type="LIMIT", quantity="1", price="70000"
            )
        )
        execute = service.modify_order
    else:
        preview = await service.preview_order_cancellation("order-1")
        execute = service.cancel_order
    await service.approve_preview(preview["preview_id"])

    with pytest.raises(OrderStateUnknownError) as exc_info:
        await execute(preview["preview_id"])
    assert exc_info.value.data["retry"] is False
    with pytest.raises(TossInvestError, match=r"does not exist|already used"):
        await execute(preview["preview_id"])
    assert sum(call["method"] == "POST" for call in client.calls) == 1


@pytest.mark.asyncio
async def test_concurrent_execution_submits_an_approved_order_once(
    trading_settings: Settings,
) -> None:
    client = StubClient()
    service = TossInvestService(trading_settings, client)
    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="005930", side="BUY", order_type="LIMIT", quantity="1", price="70000"
        )
    )
    await service.approve_preview(preview["preview_id"])
    results = await asyncio.gather(
        service.place_order(preview["preview_id"]),
        service.place_order(preview["preview_id"]),
        return_exceptions=True,
    )
    assert sum(isinstance(result, TossInvestError) for result in results) == 1
    assert sum(call["method"] == "POST" for call in client.calls) == 1


@pytest.mark.asyncio
async def test_account_identifiers_are_redacted(settings: Settings) -> None:
    service = TossInvestService(settings, StubClient())

    response = await service.list_accounts()

    assert response["data"] == [
        {
            "account_index": 1,
            "account_type": "BROKERAGE",
            "selected": True,
        }
    ]
    assert "accountNo" not in str(response)
    assert "accountSeq" not in str(response)
    assert "12345678901" not in str(response)


@pytest.mark.asyncio
async def test_korean_amount_order_is_rejected(
    trading_settings: Settings,
) -> None:
    service = TossInvestService(trading_settings, StubClient())

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
    service = TossInvestService(trading_settings, StubClient())

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
    service = TossInvestService(trading_settings, StubClient())

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
    service = TossInvestService(trading_settings, StubClient())

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
async def test_modify_and_cancel_require_separate_human_approval(
    trading_settings: Settings,
) -> None:
    client = StubClient()
    service = TossInvestService(trading_settings, client)

    modify_preview = await service.preview_order_modification(
        OrderModificationRequest(
            order_id="order-original",
            order_type="LIMIT",
            quantity="5",
            price="71000",
        )
    )
    with pytest.raises(TossInvestError) as modify_error:
        await service.modify_order(modify_preview["preview_id"])
    assert modify_error.value.code == "approval-required"

    await service.approve_preview(modify_preview["preview_id"])
    modify_result = await service.modify_order(modify_preview["preview_id"])
    assert modify_result["operation"]["data"]["orderId"] == "order-2"
    assert modify_result["order"]["data"]["orderId"] == "order-2"

    cancel_preview = await service.preview_order_cancellation("order-original")
    with pytest.raises(TossInvestError) as cancel_error:
        await service.cancel_order(cancel_preview["preview_id"])
    assert cancel_error.value.code == "approval-required"

    await service.approve_preview(cancel_preview["preview_id"])
    cancel_result = await service.cancel_order(cancel_preview["preview_id"])
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
    service = TossInvestService(trading_settings, StubClient())

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order_modification(
            OrderModificationRequest(
                order_id="order-original",
                order_type="LIMIT",
                price="71000",
            )
        )

    assert exc_info.value.code == "kr-modify-quantity-required"


@pytest.mark.asyncio
async def test_korean_market_modification_uses_upper_limit(
    trading_settings: Settings,
) -> None:
    trading_settings.tossinvest_max_order_krw = Decimal("800000")
    service = TossInvestService(trading_settings, StubClient())

    with pytest.raises(TossInvestError) as exc_info:
        await service.preview_order_modification(
            OrderModificationRequest(
                order_id="order-original",
                order_type="MARKET",
                quantity="10",
            )
        )

    assert exc_info.value.code == "configured-order-limit-exceeded"
    assert exc_info.value.data == {"estimated": "910000", "limit": "800000"}


@pytest.mark.asyncio
async def test_approved_modification_revalidates_additional_buying_power(
    trading_settings: Settings,
) -> None:
    client = DroppingBuyingPowerClient()
    service = TossInvestService(trading_settings, client)
    preview = await service.preview_order_modification(
        OrderModificationRequest(
            order_id="order-original",
            order_type="LIMIT",
            quantity="20",
            price="71000",
        )
    )
    await service.approve_preview(preview["preview_id"])

    with pytest.raises(TossInvestError) as exc_info:
        await service.modify_order(preview["preview_id"])

    assert exc_info.value.code == "insufficient-buying-power-preview"
    assert not any(call["method"] == "POST" for call in client.calls)
