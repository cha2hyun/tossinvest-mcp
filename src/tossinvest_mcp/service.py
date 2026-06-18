from __future__ import annotations

import asyncio
import secrets
import uuid
from decimal import Decimal
from typing import Any, Literal, cast

from tossinvest_mcp.client import TossInvestClient
from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.models import OrderModificationRequest, OrderPreviewRequest
from tossinvest_mcp.previews import Preview, PreviewStore
from tossinvest_mcp.settings import Settings

Market = Literal["KR", "US"]

HIGH_VALUE_KRW_LIMIT = Decimal("100000000")


class TossInvestService:
    """Business layer used by MCP tools and tests."""

    def __init__(
        self,
        settings: Settings,
        client: TossInvestClient,
        previews: PreviewStore | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.previews = previews or PreviewStore()
        self._trading_lock = asyncio.Lock()

    async def get_stock_info(self, symbols: str) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/stocks",
            group="STOCK",
            params={"symbols": self._validated_symbols(symbols)},
        )

    async def get_stock_warnings(self, symbol: str) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            f"/api/v1/stocks/{symbol}/warnings",
            group="STOCK",
        )

    async def get_prices(self, symbols: str) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/prices",
            group="MARKET_DATA",
            params={"symbols": self._validated_symbols(symbols)},
        )

    async def get_orderbook(self, symbol: str) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/orderbook",
            group="MARKET_DATA",
            params={"symbol": symbol},
        )

    async def get_recent_trades(self, symbol: str, count: int = 50) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/trades",
            group="MARKET_DATA",
            params={"symbol": symbol, "count": count},
        )

    async def get_price_limits(self, symbol: str) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/price-limits",
            group="MARKET_DATA",
            params={"symbol": symbol},
        )

    async def get_candles(
        self,
        symbol: str,
        interval: Literal["1m", "1d"],
        count: int = 100,
        before: str | None = None,
        adjusted: bool = True,
    ) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/candles",
            group="MARKET_DATA_CHART",
            params={
                "symbol": symbol,
                "interval": interval,
                "count": count,
                "before": before,
                "adjusted": adjusted,
            },
        )

    async def get_exchange_rate(
        self,
        base_currency: Literal["KRW", "USD"],
        quote_currency: Literal["KRW", "USD"],
        date_time: str | None = None,
    ) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/exchange-rate",
            group="MARKET_INFO",
            params={
                "baseCurrency": base_currency,
                "quoteCurrency": quote_currency,
                "dateTime": date_time,
            },
        )

    async def get_market_calendar(self, market: Market, date: str | None = None) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            f"/api/v1/market-calendar/{market}",
            group="MARKET_INFO",
            params={"date": date},
        )

    async def list_accounts(self) -> dict[str, Any]:
        response = await self.client.request("GET", "/api/v1/accounts", group="ACCOUNT")
        accounts = response.get("data")
        if not isinstance(accounts, list):
            raise TossInvestError(
                "The upstream account response was malformed",
                code="invalid-upstream-response",
            )
        selected_seq = self.settings.tossinvest_account_seq
        response["data"] = [
            {
                "account_type": account.get("accountType"),
                "selected": selected_seq is not None
                and str(account.get("accountSeq")) == selected_seq,
            }
            for account in accounts
            if isinstance(account, dict)
        ]
        return response

    async def get_holdings(self, symbol: str | None = None) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/holdings",
            group="ASSET",
            params={"symbol": symbol},
            account_required=True,
        )

    async def list_orders(
        self,
        status: Literal["OPEN", "CLOSED"],
        symbol: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/orders",
            group="ORDER_HISTORY",
            params={
                "status": status,
                "symbol": symbol,
                "from": from_date,
                "to": to_date,
                "cursor": cursor,
                "limit": limit,
            },
            account_required=True,
        )

    async def get_order(self, order_id: str) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            f"/api/v1/orders/{order_id}",
            group="ORDER_HISTORY",
            account_required=True,
        )

    async def get_buying_power(self, currency: Literal["KRW", "USD"]) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/buying-power",
            group="ORDER_INFO",
            params={"currency": currency},
            account_required=True,
        )

    async def get_sellable_quantity(self, symbol: str) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/sellable-quantity",
            group="ORDER_INFO",
            params={"symbol": symbol},
            account_required=True,
        )

    async def get_commissions(self) -> dict[str, Any]:
        return await self.client.request(
            "GET",
            "/api/v1/commissions",
            group="ORDER_INFO",
            account_required=True,
        )

    async def preview_order(self, request: OrderPreviewRequest) -> dict[str, Any]:
        self._ensure_trading_enabled()
        stock_response = await self.get_stock_info(request.symbol)
        stock = self._first_item(stock_response, "stock")
        price_response = await self.get_prices(request.symbol)
        price = self._first_item(price_response, "price")
        currency = cast(Literal["KRW", "USD"], stock.get("currency"))
        if currency not in {"KRW", "USD"}:
            raise TossInvestError("Unsupported stock currency", code="unsupported-currency")
        if request.order_amount is not None and currency != "USD":
            raise TossInvestError(
                "Amount-based orders are supported only for US stocks",
                code="amount-order-market-not-supported",
            )
        if request.time_in_force == "CLS" and currency != "USD":
            raise TossInvestError(
                "CLS orders are supported only for US stocks",
                code="time-in-force-market-not-supported",
            )

        market: Market = "KR" if currency == "KRW" else "US"
        warnings = await self.get_stock_warnings(request.symbol)
        calendar = await self.get_market_calendar(market)
        availability = (
            await self.get_buying_power(currency)
            if request.side == "BUY"
            else await self.get_sellable_quantity(request.symbol)
        )

        market_price = Decimal(str(price["lastPrice"]))
        estimate_price = market_price
        price_limit_data: dict[str, Any] | None = None
        if currency == "KRW" and request.order_type == "MARKET":
            price_limits = await self.get_price_limits(request.symbol)
            price_limit_data = self._mapping_data(price_limits, "price limit")
            upper_limit = price_limit_data.get("upperLimitPrice")
            if upper_limit is None:
                raise TossInvestError(
                    "A Korean market order cannot be safely estimated without an upper price limit",
                    code="market-order-limit-unavailable",
                )
            estimate_price = Decimal(str(upper_limit))

        estimated_amount = request.estimated_amount(estimate_price)
        availability_data = self._mapping_data(availability, "order availability")
        if request.side == "BUY":
            buying_power = Decimal(str(availability_data["cashBuyingPower"]))
            if estimated_amount > buying_power:
                raise TossInvestError(
                    "Estimated order amount exceeds current cash buying power",
                    code="insufficient-buying-power-preview",
                    data={
                        "estimated": str(estimated_amount),
                        "buying_power": str(buying_power),
                        "currency": currency,
                    },
                )
        else:
            sellable = Decimal(str(availability_data["sellableQuantity"]))
            estimated_quantity = (
                Decimal(request.quantity)
                if request.quantity is not None
                else Decimal(str(request.order_amount)) / market_price
            )
            if estimated_quantity > sellable:
                raise TossInvestError(
                    "Estimated sell quantity exceeds the currently sellable quantity",
                    code="insufficient-sellable-quantity-preview",
                    data={
                        "estimated_quantity": str(estimated_quantity),
                        "sellable_quantity": str(sellable),
                    },
                )
        estimated_krw = await self._enforce_order_limits(currency, estimated_amount)
        client_order_id = uuid.uuid4().hex
        api_payload = request.to_api_payload(client_order_id)
        phrase = self._confirmation_phrase("ORDER", request.symbol, request.side)
        preview = await self.previews.create("create", api_payload, phrase)

        return self._preview_response(
            preview,
            {
                "operation": "create",
                "order": api_payload,
                "stock": stock,
                "warnings": warnings["data"],
                "current_price": price,
                "price_limits": price_limit_data,
                "market_calendar": calendar["data"],
                "availability": availability_data,
                "estimated_amount": str(estimated_amount),
                "currency": currency,
                "estimated_krw": str(estimated_krw),
            },
        )

    async def place_order(self, preview_id: str, confirmation_phrase: str) -> dict[str, Any]:
        self._ensure_trading_enabled()
        async with self._trading_lock:
            preview = await self.previews.consume(
                preview_id,
                confirmation_phrase,
                expected_kind="create",
            )
            operation = await self.client.request(
                "POST",
                "/api/v1/orders",
                group="ORDER",
                json=preview.payload,
                account_required=True,
                write_operation=True,
            )
            return await self._operation_with_order_detail(operation)

    async def preview_order_modification(self, request: OrderModificationRequest) -> dict[str, Any]:
        self._ensure_trading_enabled()
        current = await self.get_order(request.order_id)
        order = self._mapping_data(current, "order")
        self._ensure_order_is_actionable(order, "modify")
        symbol = str(order["symbol"])
        currency = cast(Literal["KRW", "USD"], order["currency"])
        if currency == "KRW" and request.quantity is None:
            raise TossInvestError(
                "Quantity is required when modifying a Korean stock order",
                code="kr-modify-quantity-required",
            )
        if currency == "USD" and request.quantity is not None:
            raise TossInvestError(
                "Quantity cannot be modified for a US stock order",
                code="us-modify-quantity-not-supported",
            )
        quantity = request.quantity or str(order["quantity"])
        if request.order_type == "LIMIT":
            estimate_price = Decimal(str(request.price))
        else:
            price_response = await self.get_prices(symbol)
            estimate_price = Decimal(str(self._first_item(price_response, "price")["lastPrice"]))
        estimated_amount = Decimal(quantity) * estimate_price
        estimated_krw = await self._enforce_order_limits(currency, estimated_amount)

        payload = {
            "order_id": request.order_id,
            "body": request.to_api_payload(),
        }
        phrase = self._confirmation_phrase("MODIFY", symbol, str(order["side"]))
        preview = await self.previews.create("modify", payload, phrase)
        return self._preview_response(
            preview,
            {
                "operation": "modify",
                "current_order": order,
                "modification": payload["body"],
                "estimated_amount": str(estimated_amount),
                "currency": currency,
                "estimated_krw": str(estimated_krw),
            },
        )

    async def modify_order(self, preview_id: str, confirmation_phrase: str) -> dict[str, Any]:
        self._ensure_trading_enabled()
        async with self._trading_lock:
            preview = await self.previews.consume(
                preview_id,
                confirmation_phrase,
                expected_kind="modify",
            )
            order_id = str(preview.payload["order_id"])
            body = cast(dict[str, Any], preview.payload["body"])
            operation = await self.client.request(
                "POST",
                f"/api/v1/orders/{order_id}/modify",
                group="ORDER",
                json=body,
                account_required=True,
                write_operation=True,
            )
            return await self._operation_with_order_detail(operation)

    async def preview_order_cancellation(self, order_id: str) -> dict[str, Any]:
        self._ensure_trading_enabled()
        current = await self.get_order(order_id)
        order = self._mapping_data(current, "order")
        self._ensure_order_is_actionable(order, "cancel")
        phrase = self._confirmation_phrase(
            "CANCEL",
            str(order["symbol"]),
            str(order["side"]),
        )
        preview = await self.previews.create("cancel", {"order_id": order_id}, phrase)
        return self._preview_response(
            preview,
            {
                "operation": "cancel",
                "current_order": order,
            },
        )

    async def cancel_order(self, preview_id: str, confirmation_phrase: str) -> dict[str, Any]:
        self._ensure_trading_enabled()
        async with self._trading_lock:
            preview = await self.previews.consume(
                preview_id,
                confirmation_phrase,
                expected_kind="cancel",
            )
            order_id = str(preview.payload["order_id"])
            operation = await self.client.request(
                "POST",
                f"/api/v1/orders/{order_id}/cancel",
                group="ORDER",
                json={},
                account_required=True,
                write_operation=True,
            )
            return await self._operation_with_order_detail(operation)

    async def _operation_with_order_detail(self, operation: dict[str, Any]) -> dict[str, Any]:
        data = self._mapping_data(operation, "order operation")
        order_id = data.get("orderId")
        if not order_id:
            return {
                "operation": operation,
                "order": None,
                "warning": "The operation succeeded but the response did not contain an order ID.",
            }
        try:
            detail = await self.get_order(str(order_id))
        except TossInvestError as exc:
            return {
                "operation": operation,
                "order": None,
                "order_lookup_error": exc.as_dict()["error"],
                "warning": (
                    "The write operation succeeded but its follow-up lookup failed. "
                    "Do not repeat the write; inspect order history."
                ),
            }
        return {
            "operation": operation,
            "order": detail,
        }

    async def _enforce_order_limits(
        self,
        currency: Literal["KRW", "USD"],
        estimated_amount: Decimal,
    ) -> Decimal:
        maximum = (
            self.settings.tossinvest_max_order_krw
            if currency == "KRW"
            else self.settings.tossinvest_max_order_usd
        )
        if maximum is None:
            raise TossInvestError(
                f"Maximum order limit for {currency} is not configured",
                code="order-limit-not-configured",
            )
        if estimated_amount > maximum:
            raise TossInvestError(
                f"Estimated order amount exceeds the configured {currency} limit",
                code="configured-order-limit-exceeded",
                data={"estimated": str(estimated_amount), "limit": str(maximum)},
            )

        if currency == "KRW":
            estimated_krw = estimated_amount
        else:
            exchange = await self.get_exchange_rate("USD", "KRW")
            exchange_data = self._mapping_data(exchange, "exchange rate")
            estimated_krw = estimated_amount * Decimal(str(exchange_data["rate"]))

        if estimated_krw >= HIGH_VALUE_KRW_LIMIT:
            raise TossInvestError(
                "Orders worth KRW 100,000,000 or more are blocked",
                code="high-value-order-blocked",
                data={"estimated_krw": str(estimated_krw)},
            )
        return estimated_krw

    def _ensure_trading_enabled(self) -> None:
        if not self.settings.tossinvest_enable_trading:
            raise TossInvestError("Trading is disabled", code="trading-disabled")

    @staticmethod
    def _ensure_order_is_actionable(order: dict[str, Any], operation: str) -> None:
        status = str(order.get("status"))
        if status not in {"PENDING", "PARTIAL_FILLED"}:
            raise TossInvestError(
                f"Order status {status} cannot be used for {operation}",
                code=f"order-not-{operation}able",
                data={"status": status},
            )

    @staticmethod
    def _validated_symbols(symbols: str) -> str:
        items = symbols.split(",")
        if not items or len(items) > 200 or any(not item for item in items):
            raise TossInvestError(
                "symbols must contain 1 to 200 non-empty comma-separated symbols",
                code="invalid-symbols",
            )
        return ",".join(items)

    @staticmethod
    def _mapping_data(response: dict[str, Any], label: str) -> dict[str, Any]:
        data = response.get("data")
        if not isinstance(data, dict):
            raise TossInvestError(
                f"The upstream {label} response was malformed",
                code="invalid-upstream-response",
            )
        return data

    @classmethod
    def _first_item(cls, response: dict[str, Any], label: str) -> dict[str, Any]:
        data = response.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise TossInvestError(
                f"The upstream {label} response was empty or malformed",
                code="invalid-upstream-response",
            )
        return data[0]

    @staticmethod
    def _confirmation_phrase(operation: str, symbol: str, side: str) -> str:
        nonce = secrets.token_hex(3).upper()
        return f"CONFIRM {operation} {side} {symbol} {nonce}"

    @staticmethod
    def _preview_response(preview: Preview, summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "preview_id": preview.preview_id,
            "expires_in_seconds": 120,
            "confirmation_phrase": preview.confirmation_phrase,
            "summary": summary,
            "warning": "Review every field. The confirmation is one-time and expires in 2 minutes.",
        }
