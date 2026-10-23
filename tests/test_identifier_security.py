from __future__ import annotations

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.models import OrderModificationRequest
from tossinvest_mcp.server import create_mcp
from tossinvest_mcp.service import TossInvestService
from tossinvest_mcp.settings import Settings

from .test_service import RecordingClient

UNSAFE_ORDER_IDS = [
    "",
    ".",
    "..",
    "../accounts",
    "%2e%2e%2faccounts",
    "order?extra=1",
    "order#fragment",
    "order\\accounts",
    "order\x00",
    "order\n",
    "x" * 257,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("order_id", UNSAFE_ORDER_IDS)
async def test_order_read_services_reject_path_and_query_escape(
    settings: Settings, order_id: str
) -> None:
    upstream = RecordingClient()
    service = TossInvestService(settings, upstream)

    for method in (service.get_order, service.get_conditional_order):
        with pytest.raises(TossInvestError) as error:
            await method(order_id)
        assert error.value.code == "invalid-order-id"

    assert upstream.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("order_id", ["../accounts", "order?extra=1", "%2e%2e%2faccounts", ".."])
async def test_order_previews_reject_unsafe_ids_before_lookup(
    trading_settings: Settings, order_id: str
) -> None:
    upstream = RecordingClient()
    service = TossInvestService(trading_settings, upstream)

    with pytest.raises(TossInvestError, match="Order IDs"):
        await service.preview_order_cancellation(order_id)
    with pytest.raises(TossInvestError, match="Order IDs"):
        await service.preview_order_modification(
            OrderModificationRequest(
                order_id=order_id, order_type="LIMIT", quantity="1", price="70000"
            )
        )

    assert upstream.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("order_id", UNSAFE_ORDER_IDS)
async def test_order_tools_reject_unsafe_ids_before_service_dispatch(
    trading_settings: Settings, order_id: str
) -> None:
    upstream = RecordingClient()
    mcp, _ = create_mcp(trading_settings, client=upstream)

    async with Client(mcp) as client:
        for tool, arguments in (
            ("get_order", {"order_id": order_id}),
            ("get_conditional_order", {"conditional_order_id": order_id}),
            ("preview_order_cancellation", {"order_id": order_id}),
            (
                "preview_order_modification",
                {"order_id": order_id, "order_type": "LIMIT", "quantity": "1", "price": "70000"},
            ),
        ):
            with pytest.raises(ToolError):
                await client.call_tool(tool, arguments)

    assert upstream.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "order_id",
    ["0d5QIHjmtksbsmM-hBRAgP-ExI8iodGm9fAR5txelPfnMM8XQ_swoJdwL5RpGWMo", "order._~-1", "x" * 256],
)
async def test_url_safe_order_ids_are_preserved(settings: Settings, order_id: str) -> None:
    upstream = RecordingClient()
    mcp, _ = create_mcp(settings, client=upstream)

    async with Client(mcp) as client:
        await client.call_tool("get_order", {"order_id": order_id})
        await client.call_tool("get_conditional_order", {"conditional_order_id": order_id})

    assert [call["path"] for call in upstream.calls] == [
        f"/api/v1/orders/{order_id}",
        f"/api/v1/conditional-orders/{order_id}",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol", [".", ".."])
async def test_stock_symbol_paths_cannot_be_dot_segments(settings: Settings, symbol: str) -> None:
    upstream = RecordingClient()
    mcp, _ = create_mcp(settings, client=upstream)

    async with Client(mcp) as client:
        for tool in ("get_stock_warnings", "get_stock_investor_trading"):
            with pytest.raises(ToolError, match="invalid-symbol"):
                await client.call_tool(tool, {"symbol": symbol})

    assert upstream.calls == []
