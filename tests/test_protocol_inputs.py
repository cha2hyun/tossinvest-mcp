from __future__ import annotations

from typing import Any, Literal

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from tossinvest_mcp.server import create_mcp
from tossinvest_mcp.settings import Settings

from .test_service import RecordingClient


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_protocol_accepts_iso_dates_without_coercing_other_inputs(
    settings: Settings, mode: Literal["legacy", "2026-07-28"]
) -> None:
    upstream = RecordingClient()
    mcp, _ = create_mcp(settings, client=upstream)

    async with Client(mcp, mode=mode) as client:
        await client.call_tool("get_market_calendar", {"market": "KR", "date": "2026-10-16"})
        await client.call_tool(
            "get_candles",
            {
                "symbol": "005930",
                "interval": "1d",
                "count": 2,
                "before": "2026-10-16T15:30:00+09:00",
                "adjusted": False,
            },
        )

        assert upstream.calls[0]["params"] == {"date": "2026-10-16"}
        assert upstream.calls[1]["params"] == {
            "symbol": "005930",
            "interval": "1d",
            "count": 2,
            "before": "2026-10-16T15:30:00+09:00",
            "adjusted": False,
        }

        invalid_overrides: list[dict[str, Any]] = [
            {"count": "2"},
            {"adjusted": "true"},
            {"before": "2026-10-99T15:30:00+09:00"},
        ]
        for invalid in invalid_overrides:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "get_candles", {"symbol": "005930", "interval": "1d", **invalid}
                )
        with pytest.raises(ToolError):
            await client.call_tool("get_market_calendar", {"market": "KR", "date": "2026-10-99"})

    assert len(upstream.calls) == 2
