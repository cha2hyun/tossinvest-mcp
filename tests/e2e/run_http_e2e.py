from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

MCP_URL = "http://127.0.0.1:8000/mcp"
ALPHA_SECRET = "e2e-secret-alpha-not-real"  # noqa: S105 - test-only fake value
BETA_SECRET = "e2e-secret-beta-not-real"  # noqa: S105 - test-only fake value
SECTOR_TOOLS = {
    "list_sectors",
    "get_sector",
    "get_sector_stocks",
    "get_sector_etfs",
    "get_sector_rankings",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def transport(client_id: str, client_secret: str) -> StreamableHttpTransport:
    return StreamableHttpTransport(
        MCP_URL,
        headers={
            "X-Tossinvest-Client-Id": client_id,
            "X-Tossinvest-Client-Secret": client_secret,
        },
    )


def result_price(structured: dict[str, Any] | None) -> str:
    require(structured is not None, "get_prices returned no structured content")
    assert structured is not None
    data = structured.get("data")
    require(isinstance(data, list) and len(data) == 1, "get_prices returned unexpected data")
    assert isinstance(data, list)
    item = data[0]
    require(isinstance(item, dict), "get_prices item is not an object")
    assert isinstance(item, dict)
    value = item.get("lastPrice")
    require(isinstance(value, str), "get_prices did not return lastPrice")
    assert isinstance(value, str)
    return value


def result_object(structured: dict[str, Any] | None) -> dict[str, Any]:
    require(structured is not None, "sector tool returned no structured content")
    assert structured is not None
    data = structured.get("data")
    require(isinstance(data, dict), "sector tool returned unexpected data")
    assert isinstance(data, dict)
    return data


async def check_sector_tools(client: Client[StreamableHttpTransport]) -> None:
    sectors = await client.call_tool("list_sectors", {})
    require(
        result_object(sectors.structured_content)["sectors"]
        == [
            {"sectorId": "10", "name": "IT 하드웨어", "depth": 0, "parentSectorId": None},
            {"sectorId": "100", "name": "반도체", "depth": 1, "parentSectorId": "10"},
        ],
        "sector hierarchy or null parent changed",
    )

    detail = await client.call_tool("get_sector", {"sector_id": "100", "market_country": "KR"})
    detail_data = result_object(detail.structured_content)
    require(detail_data["sectorId"] == "100", "sector detail identifier changed")
    require(
        detail_data["performance"]["changeRates"]
        == [
            {"duration": "1d", "changeRate": "0.0179"},
            {"duration": "1w", "changeRate": "0.0412"},
            {"duration": "1mo", "changeRate": "-0.0231"},
            {"duration": "3mo", "changeRate": "0.1188"},
            {"duration": "6mo", "changeRate": None},
            {"duration": "1y", "changeRate": "0.3542"},
        ],
        "sector performance periods, decimal strings, or missing values changed",
    )

    stocks = await client.call_tool(
        "get_sector_stocks", {"sector_id": "100", "market_country": "US"}
    )
    require(
        result_object(stocks.structured_content)["stocks"]
        == [
            {
                "symbol": "NVDA",
                "name": "엔비디아",
                "volume": None,
                "tradingAmount": None,
                "marketCapitalization": "4703000000000000",
                "currency": "KRW",
            }
        ],
        "US sector stock KRW amounts or missing values changed",
    )

    etfs = await client.call_tool("get_sector_etfs", {"sector_id": "100", "market_country": "KR"})
    require(
        result_object(etfs.structured_content)["etfs"]
        == [{"symbol": "091160", "name": "KODEX 반도체"}],
        "sector ETF symbol or name changed",
    )

    for ranking_type, market_country, duration, change_rate, amount, capitalization in (
        ("TOP_GAINERS", "KR", "1d", "0.0179", None, None),
        ("MARKET_TRADING_AMOUNT", "US", "1w", "0.0412", "184200000000000", "9120000000000000"),
    ):
        rankings = await client.call_tool(
            "get_sector_rankings",
            {"ranking_type": ranking_type, "market_country": market_country, "duration": duration},
        )
        require(
            result_object(rankings.structured_content)["rankings"]
            == [
                {
                    "rank": 1,
                    "sectorId": "100",
                    "name": "반도체",
                    "changeRate": change_rate,
                    "tradingAmount": amount,
                    "marketCapitalization": capitalization,
                    "currency": "KRW",
                }
            ],
            f"{ranking_type} sector ranking or KRW currency changed",
        )


async def check_http_routes() -> None:
    async with httpx.AsyncClient(base_url="http://127.0.0.1:8000") as client:
        health = await client.get("/healthz")
        readiness = await client.get("/readyz")

    require(health.status_code == 200, f"healthz returned HTTP {health.status_code}")
    require(
        health.json() == {"status": "ok", "service": "tossinvest-mcp"},
        "healthz payload changed",
    )
    require(health.headers.get("Cache-Control") == "no-store", "security header is missing")
    require(readiness.status_code == 200, f"readyz returned HTTP {readiness.status_code}")
    require(
        readiness.json() == {"status": "ready", "credential_mode": "request-headers"},
        "readyz payload changed",
    )


async def check_mcp_and_upstream(mode: Literal["legacy", "2026-07-28"]) -> None:
    async with (
        Client(transport("e2e-client-alpha", ALPHA_SECRET), timeout=20, mode=mode) as alpha,
        Client(transport("e2e-client-beta", BETA_SECRET), timeout=20, mode=mode) as beta,
    ):
        if mode == "legacy":
            require(await alpha.ping(), "MCP ping failed")
        tools = await alpha.list_tools()
        names = {tool.name for tool in tools}
        require("get_prices" in names, "get_prices is missing from the MCP catalog")
        require("place_order" not in names, "trading tool was exposed in read-only mode")
        require(SECTOR_TOOLS <= names, "sector tools are missing from the MCP catalog")
        for tool in tools:
            if tool.name in SECTOR_TOOLS:
                require(
                    tool.annotations is not None and tool.annotations.read_only_hint is True,
                    f"{tool.name} is not marked read-only",
                )

        alpha_first = await alpha.call_tool("get_prices", {"symbols": "005930"})
        beta_result = await beta.call_tool("get_prices", {"symbols": "005930"})
        alpha_second = await alpha.call_tool("get_prices", {"symbols": "005930"})

        require(result_price(alpha_first.structured_content) == "71000", "alpha tenant leaked")
        require(result_price(beta_result.structured_content) == "72000", "beta tenant leaked")
        require(
            result_price(alpha_second.structured_content) == "71000",
            "alpha tenant changed after beta request",
        )
        await check_sector_tools(alpha)

        try:
            await alpha.call_tool("get_prices", {"symbols": "E2EERROR"})
        except ToolError as exc:
            error = str(exc)
            require("upstream-e2e-error" in error, "upstream error code was not preserved")
            require(ALPHA_SECRET not in error, "upstream error leaked the client secret")
            require("[REDACTED]" in error, "upstream secret was not visibly redacted")
        else:
            raise AssertionError("upstream error unexpectedly succeeded")


async def check_missing_credentials(mode: Literal["legacy", "2026-07-28"]) -> None:
    async with Client(StreamableHttpTransport(MCP_URL), timeout=20, mode=mode) as client:
        try:
            await client.call_tool("get_prices", {"symbols": "005930"})
        except ToolError as exc:
            require(
                "credentials-required" in str(exc),
                "missing request credentials returned the wrong MCP error",
            )
        else:
            raise AssertionError("MCP call without request credentials unexpectedly succeeded")


async def main() -> None:
    await check_http_routes()
    for mode in ("legacy", "2026-07-28"):
        await check_mcp_and_upstream(mode)
        await check_missing_credentials(mode)
    print("Hermetic Docker E2E passed")


if __name__ == "__main__":
    asyncio.run(main())
