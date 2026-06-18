from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable
from contextlib import asynccontextmanager
from datetime import date as Date
from datetime import datetime as DateTime
from typing import Annotated, Any, Literal

import uvicorn
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import StaticTokenVerifier
from pydantic import Field
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from tossinvest_mcp.client import TossInvestClient
from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.models import OrderModificationRequest, OrderPreviewRequest
from tossinvest_mcp.service import TossInvestService
from tossinvest_mcp.settings import Settings

Symbol = Annotated[str, Field(pattern=r"^[A-Za-z0-9.\-]+$")]
Symbols = Annotated[str, Field(pattern=r"^[A-Za-z0-9.,\-]+$")]


class OriginValidationMiddleware:
    """Reject browser-originated MCP requests unless the origin is allowlisted."""

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        self.app = app
        self.allowed_origins = set(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith("/mcp"):
            headers = {
                key.decode("latin-1").lower(): value.decode("latin-1")
                for key, value in scope.get("headers", [])
            }
            origin = headers.get("origin")
            if origin is not None and origin not in self.allowed_origins:
                response = JSONResponse(
                    {"error": "origin-not-allowed"},
                    status_code=403,
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_mcp(
    settings: Settings,
    *,
    client: TossInvestClient | None = None,
) -> tuple[FastMCP, TossInvestService]:
    toss_client = client or TossInvestClient(settings)
    service = TossInvestService(settings, toss_client)

    @asynccontextmanager
    async def lifespan(_: FastMCP) -> AsyncIterator[dict[str, Any]]:
        yield {"service": service}
        await toss_client.aclose()

    verifier = StaticTokenVerifier(
        tokens={
            settings.mcp_auth_token.get_secret_value(): {
                "client_id": "hermes-agent",
                "scopes": ["tossinvest"],
            }
        }
    )
    mcp = FastMCP(
        name="TossInvest",
        version="0.1.0",
        instructions=(
            "Official Toss Securities Open API tools. Trading tools are hidden unless explicitly "
            "enabled. Always preview and obtain exact user confirmation before trading."
        ),
        auth=verifier,
        lifespan=lifespan,
        mask_error_details=True,
        strict_input_validation=True,
    )

    async def tool_call(call: Awaitable[dict[str, Any]]) -> dict[str, Any]:
        try:
            return await call
        except TossInvestError as exc:
            raise ToolError(json.dumps(exc.as_dict(), ensure_ascii=False)) from exc

    @mcp.tool(tags={"market", "read"})
    async def get_stock_info(symbols: Symbols) -> dict[str, Any]:
        """Return official stock master information for up to 200 comma-separated symbols."""
        return await tool_call(service.get_stock_info(symbols))

    @mcp.tool(tags={"market", "read"})
    async def get_stock_warnings(symbol: Symbol) -> dict[str, Any]:
        """Return trading warnings and restrictions for a stock."""
        return await tool_call(service.get_stock_warnings(symbol))

    @mcp.tool(tags={"market", "read"})
    async def get_prices(symbols: Symbols) -> dict[str, Any]:
        """Return current prices for up to 200 comma-separated symbols."""
        return await tool_call(service.get_prices(symbols))

    @mcp.tool(tags={"market", "read"})
    async def get_orderbook(symbol: Symbol) -> dict[str, Any]:
        """Return the current order book for a stock."""
        return await tool_call(service.get_orderbook(symbol))

    @mcp.tool(tags={"market", "read"})
    async def get_recent_trades(
        symbol: Symbol,
        count: Annotated[int, Field(ge=1, le=50)] = 50,
    ) -> dict[str, Any]:
        """Return up to 50 recent trades for a stock."""
        return await tool_call(service.get_recent_trades(symbol, count))

    @mcp.tool(tags={"market", "read"})
    async def get_price_limits(symbol: Symbol) -> dict[str, Any]:
        """Return upper and lower price limits for a stock."""
        return await tool_call(service.get_price_limits(symbol))

    @mcp.tool(tags={"market", "read"})
    async def get_candles(
        symbol: Symbol,
        interval: Literal["1m", "1d"],
        count: Annotated[int, Field(ge=1, le=200)] = 100,
        before: DateTime | None = None,
        adjusted: bool = True,
    ) -> dict[str, Any]:
        """Return minute or daily OHLCV candles."""
        return await tool_call(
            service.get_candles(
                symbol,
                interval,
                count,
                before.isoformat() if before is not None else None,
                adjusted,
            )
        )

    @mcp.tool(tags={"market", "read"})
    async def get_exchange_rate(
        base_currency: Literal["KRW", "USD"],
        quote_currency: Literal["KRW", "USD"],
        date_time: DateTime | None = None,
    ) -> dict[str, Any]:
        """Return the KRW/USD exchange rate, optionally at a specific ISO 8601 time."""
        return await tool_call(
            service.get_exchange_rate(
                base_currency,
                quote_currency,
                date_time.isoformat() if date_time is not None else None,
            )
        )

    @mcp.tool(tags={"market", "read"})
    async def get_market_calendar(
        market: Literal["KR", "US"],
        date: Date | None = None,
    ) -> dict[str, Any]:
        """Return Korean or US market sessions for a date."""
        return await tool_call(
            service.get_market_calendar(
                market,
                date.isoformat() if date is not None else None,
            )
        )

    @mcp.tool(tags={"account", "read"})
    async def list_accounts() -> dict[str, Any]:
        """List Toss Securities accounts available to the configured API client."""
        return await tool_call(service.list_accounts())

    @mcp.tool(tags={"account", "read"})
    async def get_holdings(symbol: Symbol | None = None) -> dict[str, Any]:
        """Return holdings for the configured account, optionally filtered by symbol."""
        return await tool_call(service.get_holdings(symbol))

    @mcp.tool(tags={"order-history", "read"})
    async def list_orders(
        status: Literal["OPEN", "CLOSED"],
        symbol: Symbol | None = None,
        from_date: Date | None = None,
        to_date: Date | None = None,
        cursor: str | None = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
    ) -> dict[str, Any]:
        """List open or closed orders for the configured account."""
        return await tool_call(
            service.list_orders(
                status,
                symbol,
                from_date.isoformat() if from_date is not None else None,
                to_date.isoformat() if to_date is not None else None,
                cursor,
                limit,
            )
        )

    @mcp.tool(tags={"order-history", "read"})
    async def get_order(order_id: str) -> dict[str, Any]:
        """Return one order and its latest execution state."""
        return await tool_call(service.get_order(order_id))

    @mcp.tool(tags={"account", "read"})
    async def get_buying_power(
        currency: Literal["KRW", "USD"],
    ) -> dict[str, Any]:
        """Return cash buying power in KRW or USD."""
        return await tool_call(service.get_buying_power(currency))

    @mcp.tool(tags={"account", "read"})
    async def get_sellable_quantity(symbol: Symbol) -> dict[str, Any]:
        """Return the currently sellable quantity for a stock."""
        return await tool_call(service.get_sellable_quantity(symbol))

    @mcp.tool(tags={"account", "read"})
    async def get_commissions() -> dict[str, Any]:
        """Return Korean and US trading commission information."""
        return await tool_call(service.get_commissions())

    if settings.tossinvest_enable_trading:

        @mcp.tool(tags={"trading", "write"})
        async def preview_order(
            symbol: Symbol,
            side: Literal["BUY", "SELL"],
            order_type: Literal["LIMIT", "MARKET"],
            quantity: str | None = None,
            price: str | None = None,
            order_amount: str | None = None,
            time_in_force: Literal["DAY", "CLS"] = "DAY",
        ) -> dict[str, Any]:
            """Validate and preview an order; this does not submit it."""
            request = OrderPreviewRequest(
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                order_amount=order_amount,
                time_in_force=time_in_force,
            )
            return await tool_call(service.preview_order(request))

        @mcp.tool(tags={"trading", "write"})
        async def place_order(
            preview_id: str,
            confirmation_phrase: str,
        ) -> dict[str, Any]:
            """Submit a previously previewed order using its exact confirmation phrase."""
            return await tool_call(service.place_order(preview_id, confirmation_phrase))

        @mcp.tool(tags={"trading", "write"})
        async def preview_order_modification(
            order_id: str,
            order_type: Literal["LIMIT", "MARKET"],
            quantity: str | None = None,
            price: str | None = None,
        ) -> dict[str, Any]:
            """Validate and preview an order modification; this does not submit it."""
            request = OrderModificationRequest(
                order_id=order_id,
                order_type=order_type,
                quantity=quantity,
                price=price,
            )
            return await tool_call(service.preview_order_modification(request))

        @mcp.tool(tags={"trading", "write"})
        async def modify_order(
            preview_id: str,
            confirmation_phrase: str,
        ) -> dict[str, Any]:
            """Submit a previously previewed order modification."""
            return await tool_call(service.modify_order(preview_id, confirmation_phrase))

        @mcp.tool(tags={"trading", "write"})
        async def preview_order_cancellation(order_id: str) -> dict[str, Any]:
            """Preview cancellation of an existing order; this does not submit it."""
            return await tool_call(service.preview_order_cancellation(order_id))

        @mcp.tool(tags={"trading", "write"})
        async def cancel_order(
            preview_id: str,
            confirmation_phrase: str,
        ) -> dict[str, Any]:
            """Submit a previously previewed order cancellation."""
            return await tool_call(service.cancel_order(preview_id, confirmation_phrase))

    @mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "tossinvest-mcp"})

    @mcp.custom_route("/readyz", methods=["GET"], include_in_schema=False)
    async def readiness(_: Request) -> Response:
        ready = await toss_client.is_ready()
        return JSONResponse(
            {"status": "ready" if ready else "not-ready"},
            status_code=200 if ready else 503,
        )

    return mcp, service


def create_app() -> ASGIApp:
    settings = Settings()  # type: ignore[call-arg]
    mcp, _ = create_mcp(settings)
    middleware = [
        Middleware(
            OriginValidationMiddleware,
            allowed_origins=settings.mcp_allowed_origins,
        )
    ]
    return mcp.http_app(
        path="/mcp",
        middleware=middleware,
        stateless_http=True,
    )


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    uvicorn.run(
        create_app(),
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
        workers=1,
    )


if __name__ == "__main__":
    main()
