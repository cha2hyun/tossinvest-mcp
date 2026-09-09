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
        names = {tool.name for tool in await alpha.list_tools()}
        require("get_prices" in names, "get_prices is missing from the MCP catalog")
        require("place_order" not in names, "trading tool was exposed in read-only mode")

        alpha_first = await alpha.call_tool("get_prices", {"symbols": "005930"})
        beta_result = await beta.call_tool("get_prices", {"symbols": "005930"})
        alpha_second = await alpha.call_tool("get_prices", {"symbols": "005930"})

        require(result_price(alpha_first.structured_content) == "71000", "alpha tenant leaked")
        require(result_price(beta_result.structured_content) == "72000", "beta tenant leaked")
        require(
            result_price(alpha_second.structured_content) == "71000",
            "alpha tenant changed after beta request",
        )

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
