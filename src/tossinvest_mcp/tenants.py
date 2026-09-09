from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal

from anyio import CancelScope
from fastmcp.server.dependencies import get_http_headers
from pydantic import ValidationError

from tossinvest_mcp.client import TossInvestClient
from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.previews import Preview
from tossinvest_mcp.service import TossInvestService
from tossinvest_mcp.settings import Settings

TENANT_HEADER_NAMES = {
    "x-tossinvest-client-id",
    "x-tossinvest-client-secret",
    "x-tossinvest-account-seq",
    "x-tossinvest-account-index",
    "x-tossinvest-max-order-krw",
    "x-tossinvest-max-order-usd",
    "x-tossinvest-approval-token-sha256",
}


@dataclass
class _TenantEntry:
    service: TossInvestService
    last_used: float
    active_requests: int = 0


class TenantServiceRegistry:
    """Cache isolated Toss clients and preview state by request credential fingerprint."""

    def __init__(self, runtime: Settings, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.runtime = runtime
        self._clock = clock
        self._entries: OrderedDict[str, _TenantEntry] = OrderedDict()
        self._preview_owners: dict[str, tuple[str, Preview]] = {}
        self._service_keys: dict[int, str] = {}
        self._fingerprint_key = secrets.token_bytes(32)
        self._lock = asyncio.Lock()
        self._closed = False

    @asynccontextmanager
    async def current_service(self) -> AsyncIterator[TossInvestService]:
        headers = get_http_headers(include=TENANT_HEADER_NAMES)
        try:
            tenant_settings = Settings.from_request_headers(self.runtime, headers)
        except (ValueError, ValidationError) as exc:
            required_headers = [
                "X-Tossinvest-Client-Id",
                "X-Tossinvest-Client-Secret",
            ]
            optional_headers = ["X-Tossinvest-Account-Index"]
            if self.runtime.tossinvest_enable_trading:
                required_headers.extend(
                    [
                        "X-Tossinvest-Max-Order-Krw",
                        "X-Tossinvest-Max-Order-Usd",
                        "X-Tossinvest-Approval-Token-Sha256",
                    ]
                )
                optional_headers = ["X-Tossinvest-Account-Index"]
            raise TossInvestError(
                "Valid Toss credentials must be supplied in MCP request headers",
                code="credentials-required",
                data={
                    "required_headers": required_headers,
                    "optional_headers": optional_headers,
                },
            ) from exc

        key = self._fingerprint(tenant_settings)
        async with self._lock:
            self._ensure_open()
            await self._purge_locked()
            entry = self._entries.pop(key, None)
            if entry is None:
                await self._make_room_locked()
                client = TossInvestClient(tenant_settings)
                entry = _TenantEntry(
                    service=TossInvestService(tenant_settings, client),
                    last_used=self._clock(),
                )
                self._service_keys[id(entry.service)] = key
            else:
                entry.last_used = self._clock()
            entry.active_requests += 1
            self._entries[key] = entry
        try:
            yield entry.service
        finally:
            with CancelScope(shield=True):
                await self._release(key, entry)

    async def register_preview(
        self,
        preview_id: str,
        service: TossInvestService,
    ) -> None:
        preview = await service.previews.get(preview_id)
        async with self._lock:
            self._purge_preview_owners_locked()
            key = self._service_keys.get(id(service))
            if key is not None and key in self._entries:
                self._preview_owners[preview_id] = (key, preview)

    @asynccontextmanager
    async def service_for_preview(self, preview_id: str) -> AsyncIterator[TossInvestService]:
        async with self._lock:
            self._ensure_open()
            await self._purge_locked()
            owner = self._preview_owners.get(preview_id)
            key = owner[0] if owner is not None else None
            entry = self._entries.get(key) if key is not None else None
            if entry is None:
                raise TossInvestError(
                    "The preview does not exist or has expired",
                    code="preview-not-found",
                )
            assert key is not None
            entry.last_used = self._clock()
            entry.active_requests += 1
            self._entries.move_to_end(key)
        try:
            yield entry.service
        finally:
            with CancelScope(shield=True):
                await self._release(key, entry)

    async def close(self) -> None:
        async with self._lock:
            self._closed = True
            idle_keys = [key for key, entry in self._entries.items() if not entry.active_requests]
            entries = [self._entries.pop(key) for key in idle_keys]
            for entry in entries:
                self._service_keys.pop(id(entry.service), None)
            self._preview_owners.clear()
        await asyncio.gather(
            *(entry.service.client.aclose() for entry in entries),
            return_exceptions=True,
        )

    async def _purge_locked(self) -> None:
        self._purge_preview_owners_locked()
        cutoff = self._clock() - self.runtime.mcp_tenant_cache_ttl
        expired = [
            key
            for key, entry in self._entries.items()
            if not entry.active_requests and entry.last_used <= cutoff
        ]
        for key in expired:
            await self._remove_locked(key)

    async def _make_room_locked(self) -> None:
        if len(self._entries) < self.runtime.mcp_tenant_cache_size:
            return
        for key, entry in self._entries.items():
            if not entry.active_requests:
                await self._remove_locked(key)
                return
        raise TossInvestError(
            "All credential contexts are busy; try again after an active request finishes",
            status_code=503,
            code="tenant-capacity-exceeded",
        )

    async def _release(self, key: str, entry: _TenantEntry) -> None:
        async with self._lock:
            entry.active_requests -= 1
            entry.last_used = self._clock()
            self._entries.move_to_end(key)
            if self._closed and not entry.active_requests:
                await self._remove_locked(key)

    def _purge_preview_owners_locked(self) -> None:
        now = self._clock()
        self._preview_owners = {
            preview_id: owner
            for preview_id, owner in self._preview_owners.items()
            if owner[1].expires_at > now and not owner[1].consumed
        }

    def _ensure_open(self) -> None:
        if self._closed:
            raise TossInvestError("The server is shutting down", code="server-shutting-down")

    async def _remove_locked(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is None:
            return
        self._service_keys.pop(id(entry.service), None)
        self._preview_owners = {
            preview_id: owner
            for preview_id, owner in self._preview_owners.items()
            if owner[0] != key
        }
        await entry.service.client.aclose()

    def _fingerprint(self, settings: Settings) -> str:
        assert settings.tossinvest_client_id is not None
        assert settings.tossinvest_client_secret is not None
        fields = (
            settings.tossinvest_client_id,
            settings.tossinvest_client_secret.get_secret_value(),
            settings.tossinvest_account_seq or "",
            str(settings.tossinvest_account_index or ""),
            _decimal_text(settings.tossinvest_max_order_krw),
            _decimal_text(settings.tossinvest_max_order_usd),
            (
                settings.tossinvest_approval_token_sha256.get_secret_value()
                if settings.tossinvest_approval_token_sha256 is not None
                else ""
            ),
        )
        digest = hmac.new(self._fingerprint_key, digestmod=hashlib.sha256)
        for field in fields:
            encoded = field.encode()
            digest.update(len(encoded).to_bytes(4, "big"))
            digest.update(encoded)
        return digest.hexdigest()


def _decimal_text(value: Decimal | None) -> str:
    return "" if value is None else str(value)
