from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import SecretStr
from starlette.middleware import Middleware

from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.server import OriginValidationMiddleware, create_mcp
from tossinvest_mcp.settings import Settings

from .test_service import StubClient

READ_TOOL_NAMES = {
    "get_stock_info",
    "get_stock_warnings",
    "get_prices",
    "get_orderbook",
    "get_recent_trades",
    "get_price_limits",
    "get_candles",
    "get_exchange_rate",
    "get_market_calendar",
    "list_accounts",
    "get_holdings",
    "list_orders",
    "get_order",
    "get_buying_power",
    "get_sellable_quantity",
    "get_commissions",
}


class ErrorClient(StubClient):
    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        raise TossInvestError("safe upstream message", code="boom-code")


@pytest.mark.asyncio
async def test_read_only_server_hides_trading_tools(settings: Settings) -> None:
    mcp, _ = create_mcp(settings, client=StubClient())  # type: ignore[arg-type]
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}

    assert names == READ_TOOL_NAMES
    assert "preview_order" not in names
    assert "place_order" not in names


@pytest.mark.asyncio
async def test_trading_server_registers_preview_and_execution_tools(
    trading_settings: Settings,
) -> None:
    mcp, _ = create_mcp(trading_settings, client=StubClient())  # type: ignore[arg-type]
    names = {tool.name for tool in await mcp.list_tools()}

    assert {
        "preview_order",
        "place_order",
        "preview_order_modification",
        "modify_order",
        "preview_order_cancellation",
        "cancel_order",
    }.issubset(names)


@pytest.mark.asyncio
async def test_mcp_initialize_list_and_tool_call(settings: Settings) -> None:
    mcp, _ = create_mcp(settings, client=StubClient())  # type: ignore[arg-type]

    async with Client(mcp) as client:
        assert await client.ping() is True
        names = {tool.name for tool in await client.list_tools()}
        assert "get_prices" in names
        result = await client.call_tool("get_prices", {"symbols": "005930"})

    assert result.data["data"][0]["lastPrice"] == "70000"


@pytest.mark.asyncio
async def test_expected_upstream_error_is_returned_as_safe_tool_error(
    settings: Settings,
) -> None:
    mcp, _ = create_mcp(settings, client=ErrorClient())  # type: ignore[arg-type]

    async with Client(mcp) as client:
        with pytest.raises(ToolError, match="boom-code"):
            await client.call_tool("get_prices", {"symbols": "005930"})


@pytest.mark.asyncio
async def test_http_auth_and_origin_protection(settings: Settings) -> None:
    mcp, _ = create_mcp(settings, client=StubClient())  # type: ignore[arg-type]
    app = mcp.http_app(
        path="/mcp",
        stateless_http=True,
        middleware=[
            Middleware(
                OriginValidationMiddleware,
                allowed_origins=["https://allowed.example"],
            )
        ],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/healthz")
        blocked = await client.post(
            "/mcp",
            headers={"Origin": "https://blocked.example"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        unauthorized = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )

    assert health.status_code == 200
    assert blocked.status_code == 403
    assert unauthorized.status_code == 401


def test_trading_settings_require_limits(settings: Settings) -> None:
    values: dict[str, Any] = settings.model_dump()
    values.update(
        {
            "tossinvest_enable_trading": True,
            "tossinvest_max_order_krw": None,
            "tossinvest_max_order_usd": None,
            "mcp_auth_token": SecretStr("mcp-test-token-1234"),
        }
    )
    with pytest.raises(ValueError, match="required settings"):
        Settings(**values)


def test_allowed_origins_accept_comma_separated_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOSSINVEST_CLIENT_ID", "client")
    monkeypatch.setenv("TOSSINVEST_CLIENT_SECRET", "secret")
    monkeypatch.setenv("MCP_AUTH_TOKEN", "mcp-test-token-1234")
    monkeypatch.setenv(
        "MCP_ALLOWED_ORIGINS",
        "https://a.example, https://b.example",
    )

    settings = Settings()  # type: ignore[call-arg]

    assert settings.mcp_allowed_origins == [
        "https://a.example",
        "https://b.example",
    ]
