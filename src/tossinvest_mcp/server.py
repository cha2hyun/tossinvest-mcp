from __future__ import annotations

import argparse
import asyncio
import hashlib
import html
import json
import secrets
import sys
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date as Date
from datetime import datetime as DateTime
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import uvicorn
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import StaticTokenVerifier
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from tossinvest_mcp.client import TossInvestClient
from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.models import (
    ApiResponse,
    OrderExecutionResponse,
    OrderModificationRequest,
    OrderPreviewRequest,
    PreviewResponse,
)
from tossinvest_mcp.service import TossInvestService
from tossinvest_mcp.settings import Settings

Symbol = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9.\-]+$",
        description="KRX 6-digit symbol or US ticker.",
    ),
]
Symbols = Annotated[
    str,
    Field(
        pattern=r"^[A-Za-z0-9.,\-]+$",
        description="One to 200 comma-separated KRX symbols or US tickers.",
    ),
]
OrderId = Annotated[
    str,
    Field(min_length=1, max_length=256, description="Toss Securities order ID."),
]
PreviewId = Annotated[
    str,
    Field(
        min_length=20,
        max_length=128,
        description="Single-use preview ID returned by a preview tool.",
    ),
]
Quantity = Annotated[
    str,
    Field(
        pattern=r"^\d+$",
        max_length=30,
        description="Positive whole-share quantity.",
    ),
]
Price = Annotated[
    str,
    Field(
        pattern=r"^\d+(\.\d+)?$",
        max_length=30,
        description="Positive limit price in the stock currency.",
    ),
]
OrderAmount = Annotated[
    str,
    Field(
        pattern=r"^\d+(\.\d+)?$",
        max_length=30,
        description="Positive fixed USD amount for a US MARKET order.",
    ),
]

READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=True,
)
PREVIEW_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=True,
)
WRITE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=True,
)

API_RESPONSE_SCHEMA = TypeAdapter(ApiResponse).json_schema()
PREVIEW_RESPONSE_SCHEMA = TypeAdapter(PreviewResponse).json_schema()
ORDER_EXECUTION_RESPONSE_SCHEMA = TypeAdapter(OrderExecutionResponse).json_schema()


class ApprovalAttemptLimiter:
    """Reject repeated approval submissions instead of waiting through them."""

    def __init__(
        self,
        *,
        limit: int = 10,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def allow(self, key: str) -> bool:
        async with self._lock:
            now = self._clock()
            attempts = self._attempts[key]
            while attempts and attempts[0] <= now - self._window_seconds:
                attempts.popleft()
            if len(attempts) >= self._limit:
                return False
            attempts.append(now)
            return True


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
            "Official Toss Securities Open API tools. Prefer read-only tools and never infer a "
            "trade from analysis. Trading tools are absent unless the server is started with the "
            "explicit dangerous flag. Every write requires a separate human-approved preview. "
            "Never request approval credentials, never split orders to evade limits, and never "
            "retry a write or an order-state-unknown result automatically."
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

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_stock_info(symbols: Symbols) -> dict[str, Any]:
        """Return official stock master information for up to 200 comma-separated symbols."""
        return await tool_call(service.get_stock_info(symbols))

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_stock_warnings(symbol: Symbol) -> dict[str, Any]:
        """Return trading warnings and restrictions for a stock."""
        return await tool_call(service.get_stock_warnings(symbol))

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_prices(symbols: Symbols) -> dict[str, Any]:
        """Return current prices for up to 200 comma-separated symbols."""
        return await tool_call(service.get_prices(symbols))

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_orderbook(symbol: Symbol) -> dict[str, Any]:
        """Return the current order book for a stock."""
        return await tool_call(service.get_orderbook(symbol))

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_recent_trades(
        symbol: Symbol,
        count: Annotated[
            int,
            Field(ge=1, le=50, description="Number of recent executions to return."),
        ] = 50,
    ) -> dict[str, Any]:
        """Return up to 50 recent trades for a stock."""
        return await tool_call(service.get_recent_trades(symbol, count))

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_price_limits(symbol: Symbol) -> dict[str, Any]:
        """Return upper and lower price limits for a stock."""
        return await tool_call(service.get_price_limits(symbol))

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_candles(
        symbol: Symbol,
        interval: Annotated[
            Literal["1m", "1d"],
            Field(description="One-minute or daily candle interval."),
        ],
        count: Annotated[
            int,
            Field(ge=1, le=200, description="Number of candles to return."),
        ] = 100,
        before: Annotated[
            DateTime | None,
            Field(description="Optional exclusive ISO 8601 upper time bound."),
        ] = None,
        adjusted: Annotated[
            bool,
            Field(description="Whether daily prices should be adjusted."),
        ] = True,
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

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_exchange_rate(
        base_currency: Annotated[
            Literal["KRW", "USD"],
            Field(description="Currency being converted."),
        ],
        quote_currency: Annotated[
            Literal["KRW", "USD"],
            Field(description="Currency the rate is expressed in."),
        ],
        date_time: Annotated[
            DateTime | None,
            Field(description="Optional historical ISO 8601 time."),
        ] = None,
    ) -> dict[str, Any]:
        """Return the KRW/USD exchange rate, optionally at a specific ISO 8601 time."""
        return await tool_call(
            service.get_exchange_rate(
                base_currency,
                quote_currency,
                date_time.isoformat() if date_time is not None else None,
            )
        )

    @mcp.tool(
        tags={"market", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_market_calendar(
        market: Annotated[
            Literal["KR", "US"],
            Field(description="Korean or US market."),
        ],
        date: Annotated[
            Date | None,
            Field(description="Optional calendar date; defaults to the relevant current date."),
        ] = None,
    ) -> dict[str, Any]:
        """Return Korean or US market sessions for a date."""
        return await tool_call(
            service.get_market_calendar(
                market,
                date.isoformat() if date is not None else None,
            )
        )

    @mcp.tool(
        tags={"account", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def list_accounts() -> dict[str, Any]:
        """List Toss Securities accounts available to the configured API client."""
        return await tool_call(service.list_accounts())

    @mcp.tool(
        tags={"account", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_holdings(symbol: Symbol | None = None) -> dict[str, Any]:
        """Return holdings for the configured account, optionally filtered by symbol."""
        return await tool_call(service.get_holdings(symbol))

    @mcp.tool(
        tags={"order-history", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def list_orders(
        status: Annotated[
            Literal["OPEN", "CLOSED"],
            Field(
                description=(
                    "OPEN returns active orders without cursor paging; CLOSED returns terminal "
                    "orders and may use cursor paging."
                )
            ),
        ],
        symbol: Symbol | None = None,
        from_date: Annotated[
            Date | None,
            Field(description="Inclusive KST ordered-at start date."),
        ] = None,
        to_date: Annotated[
            Date | None,
            Field(description="Inclusive KST ordered-at end date."),
        ] = None,
        cursor: Annotated[
            str | None,
            Field(description="Opaque CLOSED-order pagination cursor; ignored for OPEN."),
        ] = None,
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=100,
                description="CLOSED page size; ignored for OPEN.",
            ),
        ] = 20,
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

    @mcp.tool(
        tags={"order-history", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_order(order_id: OrderId) -> dict[str, Any]:
        """Return one order and its latest execution state."""
        return await tool_call(service.get_order(order_id))

    @mcp.tool(
        tags={"account", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_buying_power(
        currency: Annotated[
            Literal["KRW", "USD"],
            Field(description="Currency of the requested cash buying power."),
        ],
    ) -> dict[str, Any]:
        """Return cash buying power in KRW or USD."""
        return await tool_call(service.get_buying_power(currency))

    @mcp.tool(
        tags={"account", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_sellable_quantity(symbol: Symbol) -> dict[str, Any]:
        """Return the currently sellable quantity for a stock."""
        return await tool_call(service.get_sellable_quantity(symbol))

    @mcp.tool(
        tags={"account", "read"},
        annotations=READ_ANNOTATIONS,
        output_schema=API_RESPONSE_SCHEMA,
    )
    async def get_commissions() -> dict[str, Any]:
        """Return Korean and US trading commission information."""
        return await tool_call(service.get_commissions())

    approval_attempts = ApprovalAttemptLimiter()
    global_approval_attempts = ApprovalAttemptLimiter(limit=100)

    if settings.tossinvest_enable_trading:

        @mcp.tool(
            tags={"trading", "preview"},
            annotations=PREVIEW_ANNOTATIONS,
            output_schema=PREVIEW_RESPONSE_SCHEMA,
        )
        async def preview_order(
            symbol: Symbol,
            side: Annotated[
                Literal["BUY", "SELL"],
                Field(description="Order direction."),
            ],
            order_type: Annotated[
                Literal["LIMIT", "MARKET"],
                Field(description="LIMIT requires price; MARKET forbids price."),
            ],
            quantity: Quantity | None = None,
            price: Price | None = None,
            order_amount: OrderAmount | None = None,
            time_in_force: Annotated[
                Literal["DAY", "CLS"],
                Field(description="CLS is supported only for US LIMIT orders."),
            ] = "DAY",
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

        @mcp.tool(
            tags={"trading", "write"},
            annotations=WRITE_ANNOTATIONS,
            output_schema=ORDER_EXECUTION_RESPONSE_SCHEMA,
        )
        async def place_order(preview_id: PreviewId) -> dict[str, Any]:
            """Submit a human-approved order preview. Unapproved previews are rejected."""
            return await tool_call(service.place_order(preview_id))

        @mcp.tool(
            tags={"trading", "preview"},
            annotations=PREVIEW_ANNOTATIONS,
            output_schema=PREVIEW_RESPONSE_SCHEMA,
        )
        async def preview_order_modification(
            order_id: OrderId,
            order_type: Annotated[
                Literal["LIMIT", "MARKET"],
                Field(description="Replacement order type."),
            ],
            quantity: Quantity | None = None,
            price: Price | None = None,
        ) -> dict[str, Any]:
            """Validate and preview an order modification; this does not submit it."""
            request = OrderModificationRequest(
                order_id=order_id,
                order_type=order_type,
                quantity=quantity,
                price=price,
            )
            return await tool_call(service.preview_order_modification(request))

        @mcp.tool(
            tags={"trading", "write"},
            annotations=WRITE_ANNOTATIONS,
            output_schema=ORDER_EXECUTION_RESPONSE_SCHEMA,
        )
        async def modify_order(preview_id: PreviewId) -> dict[str, Any]:
            """Submit a human-approved order modification preview."""
            return await tool_call(service.modify_order(preview_id))

        @mcp.tool(
            tags={"trading", "preview"},
            annotations=PREVIEW_ANNOTATIONS,
            output_schema=PREVIEW_RESPONSE_SCHEMA,
        )
        async def preview_order_cancellation(order_id: OrderId) -> dict[str, Any]:
            """Preview cancellation of an existing order; this does not submit it."""
            return await tool_call(service.preview_order_cancellation(order_id))

        @mcp.tool(
            tags={"trading", "write"},
            annotations=WRITE_ANNOTATIONS,
            output_schema=ORDER_EXECUTION_RESPONSE_SCHEMA,
        )
        async def cancel_order(preview_id: PreviewId) -> dict[str, Any]:
            """Submit a human-approved order cancellation preview."""
            return await tool_call(service.cancel_order(preview_id))

        @mcp.custom_route(
            "/approvals/{preview_id}",
            methods=["GET"],
            include_in_schema=False,
        )
        async def review_approval(request: Request) -> Response:
            preview_id = request.path_params["preview_id"]
            try:
                preview = await service.get_preview(preview_id)
            except TossInvestError as exc:
                return HTMLResponse(
                    _approval_error_page(str(exc)),
                    status_code=404,
                    headers=_approval_headers(),
                )
            return HTMLResponse(
                _approval_review_page(preview_id, preview.kind, preview.summary),
                headers=_approval_headers(),
            )

        @mcp.custom_route(
            "/approvals/{preview_id}",
            methods=["POST"],
            include_in_schema=False,
        )
        async def submit_approval(request: Request) -> Response:
            preview_id = request.path_params["preview_id"]
            client_key = request.client.host if request.client is not None else "unknown"
            if not await global_approval_attempts.allow(
                "global"
            ) or not await approval_attempts.allow(client_key):
                return HTMLResponse(
                    _approval_error_page("승인 시도가 너무 많습니다. 잠시 후 다시 시도하세요."),
                    status_code=429,
                    headers={**_approval_headers(), "Retry-After": "60"},
                )
            origin = request.headers.get("origin")
            expected_origin = _origin_of(settings.tossinvest_approval_base_url)
            if origin != expected_origin:
                return HTMLResponse(
                    _approval_error_page("허용되지 않은 승인 페이지 Origin입니다."),
                    status_code=403,
                    headers=_approval_headers(),
                )
            form = await request.form()
            supplied_token = str(form.get("approval_token", ""))
            decision = str(form.get("decision", ""))
            configured_hash = settings.tossinvest_approval_token_sha256
            supplied_hash = hashlib.sha256(supplied_token.encode()).hexdigest()
            if (
                not 24 <= len(supplied_token) <= 512
                or configured_hash is None
                or not secrets.compare_digest(
                    supplied_hash,
                    configured_hash.get_secret_value().lower(),
                )
            ):
                await service.record_approval_failure(preview_id)
                return HTMLResponse(
                    _approval_error_page("승인 토큰이 올바르지 않습니다."),
                    status_code=401,
                    headers=_approval_headers(),
                )
            if decision != "approve":
                return HTMLResponse(
                    _approval_error_page("주문 승인 체크박스를 선택해야 합니다."),
                    status_code=400,
                    headers=_approval_headers(),
                )
            try:
                preview = await service.approve_preview(preview_id)
            except TossInvestError as exc:
                return HTMLResponse(
                    _approval_error_page(str(exc)),
                    status_code=409,
                    headers=_approval_headers(),
                )
            return HTMLResponse(
                _approval_success_page(preview.preview_id, preview.kind),
                headers=_approval_headers(),
            )

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


def _approval_review_page(
    preview_id: str,
    kind: str,
    summary: dict[str, Any],
) -> str:
    safe_preview_id = html.escape(preview_id)
    safe_kind = html.escape(kind)
    safe_summary = html.escape(json.dumps(summary, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>토스증권 주문 승인</title>
  <style>
    body {{
      font-family: system-ui, sans-serif;
      max-width: 760px;
      margin: 40px auto;
      padding: 0 20px;
    }}
    pre {{ white-space: pre-wrap; background: #f5f6f8; padding: 16px; border-radius: 8px; }}
    .warning {{ color: #b42318; font-weight: 700; }}
    input[type=password] {{ width: 100%; padding: 10px; box-sizing: border-box; }}
    button {{ margin-top: 16px; padding: 12px 20px; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>토스증권 주문 승인</h1>
  <p class="warning">아래 주문을 직접 확인한 경우에만 승인하세요.</p>
  <p>작업: <strong>{safe_kind}</strong></p>
  <pre>{safe_summary}</pre>
  <form method="post" action="/approvals/{safe_preview_id}" autocomplete="off">
    <p>
      <label>
        <input type="checkbox" name="decision" value="approve" required>
        위 주문 내용을 확인했으며 실행을 승인합니다.
      </label>
    </p>
    <label for="approval_token">별도 승인 토큰</label>
    <input id="approval_token" name="approval_token" type="password"
           minlength="24" maxlength="512" autocomplete="new-password" required>
    <button type="submit">이 주문 승인</button>
  </form>
</body>
</html>"""


def _approval_success_page(preview_id: str, kind: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>주문 승인 완료</title></head>
<body>
  <h1>승인 완료</h1>
  <p>{html.escape(kind)} 작업이 사람에 의해 승인되었습니다.</p>
  <p>이 창을 닫고 Hermes에서 실행을 계속하세요.</p>
  <code>{html.escape(preview_id)}</code>
</body>
</html>"""


def _approval_error_page(message: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head><meta charset="utf-8"><title>주문 승인 실패</title></head>
<body><h1>승인 실패</h1><p>{html.escape(message)}</p></body>
</html>"""


def _approval_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store",
        "Content-Security-Policy": (
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        ),
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def _origin_of(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def create_app(*, dangerously_enable_trading: bool = False) -> ASGIApp:
    settings = load_server_settings(dangerously_enable_trading)
    return create_http_app(settings)


def create_http_app(settings: Settings) -> ASGIApp:
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


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tossinvest-mcp",
        description="Run the TossInvest MCP server in read-only mode by default.",
    )
    parser.add_argument(
        "--dangerously-enable-trading",
        action="store_true",
        help=(
            "DANGEROUS: register live order create, modify, and cancel tools. "
            "Human approval and order limits are still required."
        ),
    )
    return parser


def load_server_settings(dangerously_enable_trading: bool) -> Settings:
    return Settings(  # type: ignore[call-arg]
        tossinvest_enable_trading=dangerously_enable_trading
    )


def main(argv: list[str] | None = None) -> None:
    args = build_argument_parser().parse_args(argv if argv is not None else sys.argv[1:])
    settings = load_server_settings(args.dangerously_enable_trading)
    uvicorn.run(
        create_http_app(settings),
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level=settings.log_level.lower(),
        workers=1,
    )


if __name__ == "__main__":
    main()
