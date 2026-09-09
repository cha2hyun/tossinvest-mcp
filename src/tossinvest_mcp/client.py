from __future__ import annotations

import asyncio
import math
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

import httpx

from tossinvest_mcp import __version__
from tossinvest_mcp.errors import OrderStateUnknownError, TossInvestError
from tossinvest_mcp.logging_utils import redact_sensitive_values
from tossinvest_mcp.rate_limit import RateLimiter
from tossinvest_mcp.settings import Settings

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


class TossInvestClientLike(Protocol):
    async def aclose(self) -> None: ...

    async def is_ready(self) -> bool: ...

    async def request(
        self,
        method: str,
        path: str,
        *,
        group: str,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        account_required: bool = False,
        write_operation: bool = False,
    ) -> dict[str, Any]: ...


@dataclass
class _Token:
    value: str
    refresh_at: float


class TossInvestClient:
    """Async client for the official Toss Securities Open API."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if not settings.has_static_credentials:
            raise ValueError("TossInvestClient requires request or static Toss credentials")
        self.settings = settings
        self._clock = clock
        self._sleep = sleep
        self._rate_limiter = rate_limiter or RateLimiter()
        self._http = http_client or httpx.AsyncClient(
            base_url=settings.tossinvest_base_url.rstrip("/"),
            timeout=httpx.Timeout(settings.tossinvest_request_timeout),
            headers={"User-Agent": f"tossinvest-mcp/{__version__}"},
        )
        self._owns_http_client = http_client is None
        self._token: _Token | None = None
        self._token_lock = asyncio.Lock()
        self._resolved_account_seq: str | None = settings.tossinvest_account_seq
        self._account_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http.aclose()

    async def is_ready(self) -> bool:
        try:
            await self._get_access_token()
        except (httpx.HTTPError, TossInvestError):
            return False
        return True

    async def _get_access_token(self) -> str:
        now = self._clock()
        if self._token is not None and now < self._token.refresh_at:
            return self._token.value

        async with self._token_lock:
            now = self._clock()
            if self._token is not None and now < self._token.refresh_at:
                return self._token.value

            await self._rate_limiter.acquire("AUTH")
            assert self.settings.tossinvest_client_id is not None
            assert self.settings.tossinvest_client_secret is not None
            try:
                response = await self._http.post(
                    "/oauth2/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.settings.tossinvest_client_id,
                        "client_secret": self.settings.tossinvest_client_secret.get_secret_value(),
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                raise TossInvestError(
                    "Failed to issue an OAuth access token",
                    code="oauth-network-error",
                ) from exc

            payload = self._json_payload(response)
            if response.is_error:
                raise self._error_from_response(response, payload)
            try:
                token = payload["access_token"]
                raw_expiry = payload["expires_in"]
                if (
                    not isinstance(token, str)
                    or not token.strip()
                    or any(not 33 <= ord(character) <= 126 for character in token)
                    or isinstance(raw_expiry, bool)
                    or not isinstance(raw_expiry, (int, str))
                ):
                    raise ValueError("Invalid token or expiry type")
                expires_in = int(raw_expiry)
                if expires_in <= 0:
                    raise ValueError("Token expiry must be positive")
            except (KeyError, TypeError, ValueError) as exc:
                raise TossInvestError(
                    "OAuth response did not contain a valid access token",
                    status_code=response.status_code,
                    code="invalid-oauth-response",
                ) from exc

            refresh_margin = min(60, max(1, expires_in // 10))
            self._token = _Token(token, self._clock() + max(1, expires_in - refresh_margin))
            return token

    async def request(
        self,
        method: str,
        path: str,
        *,
        group: str,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
        account_required: bool = False,
        write_operation: bool = False,
    ) -> dict[str, Any]:
        account_seq = await self._get_account_seq() if account_required else None

        refreshed_after_401 = False
        retryable = method.upper() == "GET" and not write_operation
        max_attempts = 3 if retryable else 1
        attempt = 0

        while attempt < max_attempts:
            attempt += 1
            await self._rate_limiter.acquire(group)
            token = await self._get_access_token()
            headers = {"Authorization": f"Bearer {token}"}
            if account_required:
                assert account_seq is not None
                headers["X-Tossinvest-Account"] = account_seq

            try:
                response = await self._http.request(
                    method,
                    path,
                    params=self._clean_params(params),
                    json=dict(json) if json is not None else None,
                    headers=headers,
                )
            except httpx.RequestError as exc:
                if write_operation:
                    raise OrderStateUnknownError(
                        "The order request connection failed after dispatch; its state is unknown"
                    ) from exc
                raise TossInvestError(
                    "The Toss Securities API request failed",
                    code="upstream-network-error",
                ) from exc

            if write_operation and response.is_server_error:
                raise OrderStateUnknownError(
                    "The order endpoint returned a server error after dispatch; "
                    "its state is unknown"
                )

            try:
                payload = self._json_payload(response)
            except TossInvestError as exc:
                if write_operation:
                    raise OrderStateUnknownError(
                        "The order response was malformed after dispatch; its state is unknown"
                    ) from exc
                raise
            error_code = self._extract_error(payload).get("code")

            if response.status_code == 401 and error_code == "expired-token":
                if self._token is not None and self._token.value == token:
                    self._token = None
                if not retryable or refreshed_after_401 or attempt >= max_attempts:
                    raise self._error_from_response(response, payload, request_token=token)
                refreshed_after_401 = True
                continue

            if response.status_code == 429 and retryable and attempt < max_attempts:
                retry_after = self._retry_after(response, attempt)
                await self._sleep(retry_after)
                continue

            if response.is_error:
                raise self._error_from_response(response, payload, request_token=token)

            if not response.is_success:
                if write_operation:
                    raise OrderStateUnknownError(
                        "The order endpoint returned an unexpected response; its state is unknown"
                    )
                raise self._error_from_response(response, payload, request_token=token)

            return self._normalize_response(response, payload, request_token=token)

        raise TossInvestError("The Toss Securities API request exhausted its retry budget")

    async def _get_account_seq(self) -> str:
        if self._resolved_account_seq is not None:
            return self._resolved_account_seq

        async with self._account_lock:
            if self._resolved_account_seq is not None:
                return self._resolved_account_seq

            response = await self.request(
                "GET",
                "/api/v1/accounts",
                group="ACCOUNT",
            )
            raw_accounts = response.get("data")
            accounts = (
                [
                    account
                    for account in raw_accounts
                    if isinstance(account, Mapping) and account.get("accountSeq") is not None
                ]
                if isinstance(raw_accounts, list)
                else []
            )
            if not accounts:
                raise TossInvestError(
                    "No usable Toss Securities account was returned",
                    code="account-not-found",
                )

            selected_index = self.settings.tossinvest_account_index
            if selected_index is None:
                if len(accounts) != 1:
                    raise TossInvestError(
                        "Multiple accounts are available; select an account index in the MCP "
                        "connection headers",
                        code="account-selection-required",
                        data={
                            "account_count": len(accounts),
                            "accounts": [
                                {
                                    "account_index": index,
                                    "account_type": account.get("accountType"),
                                }
                                for index, account in enumerate(accounts, start=1)
                            ],
                            "header": "X-Tossinvest-Account-Index",
                        },
                    )
                selected_index = 1

            if selected_index > len(accounts):
                raise TossInvestError(
                    "The selected account index is outside the available account list",
                    code="invalid-account-selection",
                    data={
                        "selected_index": selected_index,
                        "account_count": len(accounts),
                    },
                )

            self._resolved_account_seq = str(accounts[selected_index - 1]["accountSeq"])
            return self._resolved_account_seq

    @staticmethod
    def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if params is None:
            return None
        return {key: value for key, value in params.items() if value is not None}

    @staticmethod
    def _json_payload(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            return payload
        if response.is_error:
            return {}
        raise TossInvestError(
            "The Toss Securities API response was not a JSON object",
            status_code=response.status_code,
            code="invalid-upstream-response",
        )

    @staticmethod
    def _extract_error(payload: Mapping[str, Any]) -> dict[str, Any]:
        error = payload.get("error")
        return dict(error) if isinstance(error, Mapping) else {}

    def _error_from_response(
        self,
        response: httpx.Response,
        payload: Mapping[str, Any],
        *,
        request_token: str = "",
    ) -> TossInvestError:
        error = self._extract_error(payload)
        secrets = (*self._sensitive_values(), request_token)
        request_id = (
            str(error.get("requestId"))
            if error.get("requestId")
            else response.headers.get("X-Request-Id") or response.headers.get("cf-ray")
        )
        message = error.get("message") or (
            f"Toss Securities API returned HTTP {response.status_code}"
        )
        return TossInvestError(
            str(redact_sensitive_values(str(message), secrets)),
            status_code=response.status_code,
            code=str(redact_sensitive_values(str(error.get("code") or "upstream-error"), secrets)),
            request_id=redact_sensitive_values(request_id, secrets),
            data=redact_sensitive_values(error.get("data"), secrets),
        )

    def _sensitive_values(self) -> tuple[str, ...]:
        return (
            *self._credential_values(),
            self._resolved_account_seq or "",
        )

    def _credential_values(self) -> tuple[str, ...]:
        assert self.settings.tossinvest_client_id is not None
        assert self.settings.tossinvest_client_secret is not None
        return (
            self.settings.tossinvest_client_id,
            self.settings.tossinvest_client_secret.get_secret_value(),
            self._token.value if self._token is not None else "",
        )

    @staticmethod
    def _retry_after(response: httpx.Response, attempt: int) -> float:
        raw = response.headers.get("Retry-After")
        if raw is not None:
            try:
                delay = float(raw)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(raw)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    delay = (retry_at - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = math.nan
            if math.isfinite(delay):
                return min(60.0, max(0.0, delay))
        return float(
            min(4.0, (2 ** (attempt - 1)) + random.uniform(0.0, 0.25))  # noqa: S311
        )

    def _normalize_response(
        self,
        response: httpx.Response,
        payload: Mapping[str, Any],
        *,
        request_token: str = "",
    ) -> dict[str, Any]:
        normalized = {
            "data": payload.get("result", payload),
            "meta": {
                "request_id": response.headers.get("X-Request-Id")
                or response.headers.get("cf-ray"),
                "retrieved_at": datetime.now(UTC).isoformat(),
                "rate_limit": {
                    "limit": response.headers.get("X-RateLimit-Limit"),
                    "remaining": response.headers.get("X-RateLimit-Remaining"),
                    "reset": response.headers.get("X-RateLimit-Reset"),
                },
            },
        }
        return dict(
            redact_sensitive_values(
                normalized,
                (*self._credential_values(), request_token),
                redact_accounts=False,
            )
        )
