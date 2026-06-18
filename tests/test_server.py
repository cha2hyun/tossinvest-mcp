from __future__ import annotations

import hashlib
import json
from typing import Any

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pydantic import SecretStr
from starlette.middleware import Middleware

from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.models import OrderPreviewRequest
from tossinvest_mcp.server import (
    OriginValidationMiddleware,
    build_argument_parser,
    create_mcp,
    load_server_settings,
)
from tossinvest_mcp.settings import Settings

from .conftest import APPROVAL_TOKEN
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


def test_dangerous_trading_flag_is_explicit() -> None:
    parser = build_argument_parser()

    assert parser.parse_args([]).dangerously_enable_trading is False
    assert parser.parse_args(["--dangerously-enable-trading"]).dangerously_enable_trading is True


def test_trading_environment_variable_cannot_enable_server_without_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOSSINVEST_CLIENT_ID", "client")
    monkeypatch.setenv("TOSSINVEST_CLIENT_SECRET", "secret")
    monkeypatch.setenv("TOSSINVEST_ACCOUNT_SEQ", "1")
    monkeypatch.setenv("TOSSINVEST_ENABLE_TRADING", "true")
    monkeypatch.setenv("TOSSINVEST_MAX_ORDER_KRW", "1000000")
    monkeypatch.setenv("TOSSINVEST_MAX_ORDER_USD", "1000")
    monkeypatch.setenv(
        "TOSSINVEST_APPROVAL_TOKEN_SHA256",
        hashlib.sha256(APPROVAL_TOKEN.encode()).hexdigest(),
    )
    monkeypatch.setenv("MCP_AUTH_TOKEN", "mcp-test-token-1234")

    settings = load_server_settings(False)

    assert settings.tossinvest_enable_trading is False


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
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    for name in ("place_order", "modify_order", "cancel_order"):
        properties = tools[name].parameters["properties"]
        assert set(properties) == {"preview_id"}
        assert "confirmation_phrase" not in properties

    for name in READ_TOOL_NAMES:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is True
        assert annotations.idempotentHint is True
        assert annotations.openWorldHint is True
        assert tools[name].output_schema is not None

    for name in (
        "preview_order",
        "preview_order_modification",
        "preview_order_cancellation",
    ):
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is False
        assert annotations.idempotentHint is False

    for name in ("place_order", "modify_order", "cancel_order"):
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.readOnlyHint is False
        assert annotations.destructiveHint is True
        assert annotations.idempotentHint is False

    preview_properties = tools["preview_order"].parameters["properties"]
    assert "whole-share quantity" in preview_properties["quantity"]["anyOf"][0]["description"]
    assert "US MARKET" in preview_properties["order_amount"]["anyOf"][0]["description"]
    assert tools["preview_order"].output_schema is not None
    assert tools["place_order"].output_schema is not None


@pytest.mark.asyncio
async def test_server_exposes_no_secret_resources_prompts_or_tool_inputs(
    trading_settings: Settings,
) -> None:
    mcp, _ = create_mcp(trading_settings, client=StubClient())  # type: ignore[arg-type]
    tools = await mcp.list_tools()
    serialized = json.dumps(
        [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "output_schema": tool.output_schema,
            }
            for tool in tools
        ]
    ).lower()

    assert await mcp.list_resources() == []
    assert await mcp.list_prompts() == []
    for forbidden in (
        "mcp_auth_token",
        "tossinvest_client_secret",
        "tossinvest_approval_token_sha256",
        "approval_token",
        "authorization",
    ):
        assert forbidden not in serialized
    assert "never retry a write" in mcp.instructions.lower()


@pytest.mark.asyncio
async def test_human_approval_route_is_separate_from_mcp(
    trading_settings: Settings,
) -> None:
    mcp, service = create_mcp(
        trading_settings,
        client=StubClient(),  # type: ignore[arg-type]
    )
    preview = await service.preview_order(
        OrderPreviewRequest(
            symbol="005930",
            side="BUY",
            order_type="LIMIT",
            quantity="1",
            price="70000",
        )
    )
    app = mcp.http_app(path="/mcp", stateless_http=True)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        review = await client.get(f"/approvals/{preview['preview_id']}")
        wrong = await client.post(
            f"/approvals/{preview['preview_id']}",
            headers={"Origin": "http://127.0.0.1:8000"},
            data={
                "decision": "approve",
                "approval_token": "wrong-token",
            },
        )
        cross_origin = await client.post(
            f"/approvals/{preview['preview_id']}",
            headers={"Origin": "https://attacker.example"},
            data={
                "decision": "approve",
                "approval_token": APPROVAL_TOKEN,
            },
        )
        missing_origin = await client.post(
            f"/approvals/{preview['preview_id']}",
            data={
                "decision": "approve",
                "approval_token": APPROVAL_TOKEN,
            },
        )

        assert review.status_code == 200
        assert "삼성전자" in review.text
        assert wrong.status_code == 401
        assert cross_origin.status_code == 403
        assert missing_origin.status_code == 403
        with pytest.raises(TossInvestError) as exc_info:
            await service.place_order(preview["preview_id"])
        assert exc_info.value.code == "approval-required"

        approved = await client.post(
            f"/approvals/{preview['preview_id']}",
            headers={"Origin": "http://127.0.0.1:8000"},
            data={
                "decision": "approve",
                "approval_token": APPROVAL_TOKEN,
            },
        )

    assert approved.status_code == 200
    result = await service.place_order(preview["preview_id"])
    assert result["operation"]["data"]["orderId"] == "order-1"


@pytest.mark.asyncio
async def test_approval_route_rate_limits_repeated_submissions(
    trading_settings: Settings,
) -> None:
    mcp, _ = create_mcp(
        trading_settings,
        client=StubClient(),  # type: ignore[arg-type]
    )
    app = mcp.http_app(path="/mcp", stateless_http=True)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [
            await client.post(
                f"/approvals/nonexistent-{attempt}",
                headers={"Origin": "http://127.0.0.1:8000"},
                data={"decision": "approve", "approval_token": "wrong-token-value-123456"},
            )
            for attempt in range(11)
        ]

    assert all(response.status_code == 401 for response in responses[:10])
    assert responses[10].status_code == 429
    assert responses[10].headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_date_and_datetime_inputs_use_openapi_formats(settings: Settings) -> None:
    mcp, _ = create_mcp(settings, client=StubClient())  # type: ignore[arg-type]
    tools = {tool.name: tool for tool in await mcp.list_tools()}

    def formats(tool_name: str, parameter_name: str) -> set[str]:
        parameter = tools[tool_name].parameters["properties"][parameter_name]
        variants = parameter.get("anyOf", [parameter])
        return {variant["format"] for variant in variants if "format" in variant}

    assert formats("get_candles", "before") == {"date-time"}
    assert formats("get_exchange_rate", "date_time") == {"date-time"}
    assert formats("get_market_calendar", "date") == {"date"}
    assert formats("list_orders", "from_date") == {"date"}


@pytest.mark.asyncio
async def test_mcp_initialize_list_and_tool_call(settings: Settings) -> None:
    mcp, _ = create_mcp(settings, client=StubClient())  # type: ignore[arg-type]

    async with Client(mcp) as client:
        assert await client.ping() is True
        names = {tool.name for tool in await client.list_tools()}
        assert "get_prices" in names
        result = await client.call_tool("get_prices", {"symbols": "005930"})

    assert result.structured_content["data"][0]["lastPrice"] == "70000"


@pytest.mark.asyncio
async def test_mcp_trading_tools_return_structured_preview_and_execution(
    trading_settings: Settings,
) -> None:
    mcp, service = create_mcp(
        trading_settings,
        client=StubClient(),  # type: ignore[arg-type]
    )

    async with Client(mcp) as client:
        preview_result = await client.call_tool(
            "preview_order",
            {
                "symbol": "005930",
                "side": "BUY",
                "order_type": "LIMIT",
                "quantity": "1",
                "price": "70000",
            },
        )
        preview_id = preview_result.structured_content["preview_id"]
        await service.approve_preview(preview_id)
        execution_result = await client.call_tool("place_order", {"preview_id": preview_id})

    assert preview_result.structured_content["status"] == "pending_human_approval"
    assert execution_result.structured_content["operation"]["data"]["orderId"] == "order-1"


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


def test_trading_approval_token_must_be_separate(
    trading_settings: Settings,
) -> None:
    values: dict[str, Any] = trading_settings.model_dump()
    shared_token = "shared-human-agent-token-123456"  # noqa: S105 - test-only value
    values["mcp_auth_token"] = SecretStr(shared_token)
    values["tossinvest_approval_token_sha256"] = SecretStr(
        hashlib.sha256(shared_token.encode()).hexdigest()
    )

    with pytest.raises(ValueError, match="must be different"):
        Settings(**values)


def test_mcp_token_must_differ_from_toss_client_secret(settings: Settings) -> None:
    values: dict[str, Any] = settings.model_dump()
    values["tossinvest_client_secret"] = SecretStr("shared-credential-value")
    values["mcp_auth_token"] = SecretStr("shared-credential-value")

    with pytest.raises(ValueError, match="MCP_AUTH_TOKEN must be different"):
        Settings(**values)


def test_approval_hash_accepts_secretstr_and_rejects_invalid_hex(
    trading_settings: Settings,
) -> None:
    assert (
        len(
            trading_settings.tossinvest_approval_token_sha256.get_secret_value()  # type: ignore[union-attr]
        )
        == 64
    )
    values: dict[str, Any] = trading_settings.model_dump()
    values["tossinvest_approval_token_sha256"] = SecretStr("not-a-sha256")

    with pytest.raises(ValueError, match="SHA-256 hex digest"):
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
