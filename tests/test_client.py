from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any, cast

import httpx
import pytest

from tossinvest_mcp.client import TossInvestClient
from tossinvest_mcp.errors import OrderStateUnknownError, TossInvestError
from tossinvest_mcp.rate_limit import RateLimiter
from tossinvest_mcp.settings import Settings


class NoopRateLimiter(RateLimiter):
    async def acquire(self, group: str) -> None:
        return None


def make_http_client(
    handler: Callable[
        [httpx.Request],
        httpx.Response | Coroutine[Any, Any, httpx.Response],
    ],
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://openapi.test",
        transport=httpx.MockTransport(cast(Any, handler)),
    )


@pytest.mark.asyncio
async def test_oauth_token_is_cached_and_account_header_is_applied(
    settings: Settings,
) -> None:
    token_calls = 0
    account_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/oauth2/token":
            token_calls += 1
            return httpx.Response(
                200,
                json={"access_token": "access-token", "token_type": "Bearer", "expires_in": 3600},
            )
        account_headers.append(request.headers.get("X-Tossinvest-Account"))
        return httpx.Response(200, json={"result": {"ok": True}})

    http = make_http_client(handler)
    client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())
    await client.request(
        "GET",
        "/api/v1/holdings",
        group="ASSET",
        account_required=True,
    )
    await client.request(
        "GET",
        "/api/v1/holdings",
        group="ASSET",
        account_required=True,
    )

    assert token_calls == 1
    assert account_headers == ["1", "1"]
    await http.aclose()


@pytest.mark.asyncio
async def test_single_account_is_discovered_after_oauth_without_sequence(
    settings: Settings,
) -> None:
    values = settings.model_dump()
    values["tossinvest_account_seq"] = None
    values["tossinvest_account_index"] = None
    automatic_settings = Settings(**values)
    account_headers: list[str | None] = []
    account_list_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal account_list_calls
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "access-token", "expires_in": 3600},
            )
        if request.url.path == "/api/v1/accounts":
            account_list_calls += 1
            return httpx.Response(
                200,
                json={
                    "result": [
                        {
                            "accountSeq": 7,
                            "accountNo": "1234567890",
                            "accountType": "BROKERAGE",
                        }
                    ]
                },
            )
        account_headers.append(request.headers.get("X-Tossinvest-Account"))
        return httpx.Response(200, json={"result": {"ok": True}})

    http = make_http_client(handler)
    client = TossInvestClient(
        automatic_settings,
        http_client=http,
        rate_limiter=NoopRateLimiter(),
    )

    await client.request("GET", "/api/v1/holdings", group="ASSET", account_required=True)
    await client.request("GET", "/api/v1/holdings", group="ASSET", account_required=True)

    assert account_list_calls == 1
    assert account_headers == ["7", "7"]
    await http.aclose()


@pytest.mark.asyncio
async def test_multiple_accounts_require_non_secret_account_index(
    settings: Settings,
) -> None:
    values = settings.model_dump()
    values["tossinvest_account_seq"] = None
    values["tossinvest_account_index"] = None
    automatic_settings = Settings(**values)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "access-token", "expires_in": 3600},
            )
        if request.url.path == "/api/v1/accounts":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"accountSeq": 7, "accountType": "BROKERAGE"},
                        {"accountSeq": 9, "accountType": "ISA"},
                    ]
                },
            )
        raise AssertionError(f"Unexpected request: {request.url.path}")

    http = make_http_client(handler)
    client = TossInvestClient(
        automatic_settings,
        http_client=http,
        rate_limiter=NoopRateLimiter(),
    )

    with pytest.raises(TossInvestError) as exc_info:
        await client.request(
            "GET",
            "/api/v1/holdings",
            group="ASSET",
            account_required=True,
        )

    assert exc_info.value.code == "account-selection-required"
    assert exc_info.value.data["accounts"] == [
        {"account_index": 1, "account_type": "BROKERAGE"},
        {"account_index": 2, "account_type": "ISA"},
    ]
    assert "accountSeq" not in str(exc_info.value.as_dict())
    await http.aclose()


@pytest.mark.asyncio
async def test_account_index_selects_from_discovered_accounts(settings: Settings) -> None:
    values = settings.model_dump()
    values["tossinvest_account_seq"] = None
    values["tossinvest_account_index"] = 2
    automatic_settings = Settings(**values)
    selected_header: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal selected_header
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "access-token", "expires_in": 3600},
            )
        if request.url.path == "/api/v1/accounts":
            return httpx.Response(
                200,
                json={
                    "result": [
                        {"accountSeq": 7, "accountType": "BROKERAGE"},
                        {"accountSeq": 9, "accountType": "ISA"},
                    ]
                },
            )
        selected_header = request.headers.get("X-Tossinvest-Account")
        return httpx.Response(200, json={"result": {"ok": True}})

    http = make_http_client(handler)
    client = TossInvestClient(
        automatic_settings,
        http_client=http,
        rate_limiter=NoopRateLimiter(),
    )

    await client.request("GET", "/api/v1/holdings", group="ASSET", account_required=True)

    assert selected_header == "9"
    await http.aclose()


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_token_refresh(settings: Settings) -> None:
    token_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        if request.url.path == "/oauth2/token":
            token_calls += 1
            await asyncio.sleep(0.01)
            return httpx.Response(
                200,
                json={"access_token": "access-token", "token_type": "Bearer", "expires_in": 3600},
            )
        return httpx.Response(200, json={"result": {"ok": True}})

    http = make_http_client(handler)
    client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())
    await asyncio.gather(
        *[client.request("GET", "/api/v1/prices", group="MARKET_DATA") for _ in range(5)]
    )

    assert token_calls == 1
    await http.aclose()


@pytest.mark.asyncio
async def test_get_retries_429_using_retry_after(settings: Settings) -> None:
    price_calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal price_calls
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "access-token", "token_type": "Bearer", "expires_in": 3600},
            )
        price_calls += 1
        if price_calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "0.25"},
                json={"error": {"code": "rate-limit-exceeded", "message": "slow down"}},
            )
        return httpx.Response(
            200,
            headers={"X-Request-Id": "request-1", "X-RateLimit-Remaining": "4"},
            json={"result": [{"symbol": "005930", "lastPrice": "70000"}]},
        )

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    http = make_http_client(handler)
    client = TossInvestClient(
        settings,
        http_client=http,
        rate_limiter=NoopRateLimiter(),
        sleep=fake_sleep,
    )
    result = await client.request(
        "GET",
        "/api/v1/prices",
        group="MARKET_DATA",
        params={"symbols": "005930"},
    )

    assert price_calls == 2
    assert sleeps == [0.25]
    assert result["meta"]["request_id"] == "request-1"
    await http.aclose()


@pytest.mark.asyncio
async def test_write_network_failure_is_reported_as_unknown(
    settings: Settings,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(
                200,
                json={"access_token": "access-token", "token_type": "Bearer", "expires_in": 3600},
            )
        raise httpx.ReadTimeout("timed out", request=request)

    http = make_http_client(handler)
    client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())

    with pytest.raises(OrderStateUnknownError) as exc_info:
        await client.request(
            "POST",
            "/api/v1/orders",
            group="ORDER",
            json={"symbol": "005930"},
            account_required=True,
            write_operation=True,
        )

    assert exc_info.value.code == "order-state-unknown"
    assert exc_info.value.data["retry"] is False
    await http.aclose()


@pytest.mark.asyncio
async def test_write_is_not_retried_when_token_is_reported_expired(
    settings: Settings,
) -> None:
    token_calls = 0
    order_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, order_calls
        if request.url.path == "/oauth2/token":
            token_calls += 1
            return httpx.Response(
                200,
                json={"access_token": "access-token", "token_type": "Bearer", "expires_in": 3600},
            )
        order_calls += 1
        return httpx.Response(
            401,
            json={"error": {"code": "expired-token", "message": "expired"}},
        )

    http = make_http_client(handler)
    client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())

    with pytest.raises(TossInvestError) as exc_info:
        await client.request(
            "POST",
            "/api/v1/orders",
            group="ORDER",
            json={"symbol": "005930"},
            account_required=True,
            write_operation=True,
        )

    assert exc_info.value.code == "expired-token"
    assert token_calls == 1
    assert order_calls == 1
    await http.aclose()


@pytest.mark.asyncio
async def test_read_refreshes_an_expired_token_once(settings: Settings) -> None:
    token_calls = 0
    price_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, price_calls
        if request.url.path == "/oauth2/token":
            token_calls += 1
            return httpx.Response(
                200,
                json={
                    "access_token": f"access-token-{token_calls}",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        price_calls += 1
        if price_calls == 1:
            return httpx.Response(
                401,
                json={"error": {"code": "expired-token", "message": "expired"}},
            )
        assert request.headers["Authorization"] == "Bearer access-token-2"
        return httpx.Response(200, json={"result": [{"symbol": "005930"}]})

    http = make_http_client(handler)
    client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())
    await client.request("GET", "/api/v1/prices", group="MARKET_DATA")

    assert token_calls == 2
    assert price_calls == 2
    await http.aclose()


@pytest.mark.asyncio
async def test_late_401_does_not_discard_a_newer_token(settings: Settings) -> None:
    token_calls = 0
    expired_requests = 0
    both_dispatched = asyncio.Event()
    refreshed = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, expired_requests
        if request.url.path == "/oauth2/token":
            token_calls += 1
            if token_calls == 2:
                refreshed.set()
            return httpx.Response(
                200, json={"access_token": f"token-{token_calls}", "expires_in": 3600}
            )
        if request.headers["Authorization"] == "Bearer token-1":
            expired_requests += 1
            if expired_requests == 2:
                both_dispatched.set()
                await refreshed.wait()
            else:
                await both_dispatched.wait()
            return httpx.Response(401, json={"error": {"code": "expired-token"}})
        assert request.headers["Authorization"] == "Bearer token-2"
        return httpx.Response(200, json={"result": {"ok": True}})

    async with make_http_client(handler) as http:
        client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())
        await asyncio.wait_for(
            asyncio.gather(
                client.request("GET", "/api/v1/prices", group="MARKET_DATA"),
                client.request("GET", "/api/v1/prices", group="MARKET_DATA"),
            ),
            timeout=2,
        )
    assert token_calls == 2
    assert expired_requests == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"access_token": None, "expires_in": 3600},
        {"access_token": 42, "expires_in": 3600},
        {"access_token": "", "expires_in": 3600},
        {"access_token": "unsafe\r\nheader", "expires_in": 3600},
        {"access_token": "token", "expires_in": 0},
        {"access_token": "token", "expires_in": -1},
        {"access_token": "token", "expires_in": True},
        {"access_token": "token", "expires_in": 1.5},
        {"access_token": "token", "expires_in": "invalid"},
    ],
)
async def test_invalid_oauth_response_is_rejected(
    settings: Settings, payload: dict[str, Any]
) -> None:
    async with make_http_client(lambda _: httpx.Response(200, json=payload)) as http:
        client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())
        with pytest.raises(TossInvestError) as exc_info:
            await client.request("GET", "/api/v1/prices", group="MARKET_DATA")
    assert exc_info.value.code == "invalid-oauth-response"


@pytest.mark.asyncio
@pytest.mark.parametrize("write_operation", [False, True])
async def test_protocol_failure_is_normalized_without_retry(
    settings: Settings, write_operation: bool
) -> None:
    request_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_calls
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        request_calls += 1
        raise httpx.RemoteProtocolError("connection closed with client-secret", request=request)

    async with make_http_client(handler) as http:
        client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())
        with pytest.raises(TossInvestError) as exc_info:
            await client.request(
                "POST" if write_operation else "GET",
                "/api/v1/orders",
                group="ORDER",
                write_operation=write_operation,
            )
    expected = "order-state-unknown" if write_operation else "upstream-network-error"
    assert exc_info.value.code == expected
    assert "client-secret" not in str(exc_info.value.as_dict())
    assert request_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 502, 503])
@pytest.mark.parametrize("write_operation", [False, True])
async def test_malformed_and_server_error_responses_are_not_reported_as_success(
    settings: Settings, status_code: int, write_operation: bool
) -> None:
    request_calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_calls
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        request_calls += 1
        return httpx.Response(status_code, text="<html>client-secret gateway response</html>")

    async with make_http_client(handler) as http:
        client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())
        with pytest.raises(TossInvestError) as exc_info:
            await client.request(
                "POST" if write_operation else "GET",
                "/api/v1/orders",
                group="ORDER",
                write_operation=write_operation,
            )
    if write_operation:
        assert exc_info.value.code == "order-state-unknown"
        assert exc_info.value.data["retry"] is False
    else:
        expected = "invalid-upstream-response" if status_code == 200 else "upstream-error"
        assert exc_info.value.code == expected
    assert "client-secret" not in str(exc_info.value.as_dict())
    assert request_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 400])
async def test_response_metadata_and_error_fields_redact_credentials(
    settings: Settings, status_code: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "token-value", "expires_in": 3600})
        return httpx.Response(
            status_code,
            headers={"X-Request-Id": "client-secret", "X-RateLimit-Remaining": "token-value"},
            json={
                "result": {"ok": True},
                "error": {"code": "client-secret", "requestId": "token-value"},
            },
        )

    async with make_http_client(handler) as http:
        client = TossInvestClient(settings, http_client=http, rate_limiter=NoopRateLimiter())
        if status_code == 200:
            result = await client.request("GET", "/api/v1/prices", group="MARKET_DATA")
        else:
            with pytest.raises(TossInvestError) as exc_info:
                await client.request("GET", "/api/v1/prices", group="MARKET_DATA")
            result = exc_info.value.as_dict()
    assert "client-secret" not in str(result)
    assert "token-value" not in str(result)
    assert "[REDACTED]" in str(result)


@pytest.mark.parametrize("header", ["NaN", "Infinity", "-Infinity", "99999999", "invalid"])
def test_retry_after_cannot_create_an_unbounded_wait(header: str) -> None:
    delay = TossInvestClient._retry_after(httpx.Response(429, headers={"Retry-After": header}), 1)
    assert math.isfinite(delay)
    assert 0 <= delay <= 60


def test_retry_after_supports_http_dates() -> None:
    retry_at = datetime.now(UTC) + timedelta(seconds=30)
    response = httpx.Response(429, headers={"Retry-After": format_datetime(retry_at, usegmt=True)})
    assert 28 <= TossInvestClient._retry_after(response, 1) <= 30
