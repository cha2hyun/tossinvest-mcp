from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from tossinvest_mcp.errors import TossInvestError

PreviewKind = Literal["create", "modify", "cancel"]


@dataclass
class Preview:
    preview_id: str
    kind: PreviewKind
    payload: dict[str, Any]
    summary: dict[str, Any]
    expires_at: float
    expires_at_iso: str
    approved: bool = False
    approved_at: str | None = None
    failed_approval_attempts: int = 0
    consumed: bool = False


class PreviewStore:
    """In-memory, one-time confirmation store for trading operations."""

    def __init__(
        self,
        *,
        ttl_seconds: int = 120,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: dict[str, Preview] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        kind: PreviewKind,
        payload: Mapping[str, Any],
        summary: Mapping[str, Any],
    ) -> Preview:
        async with self._lock:
            self._purge_expired()
            now = self._clock()
            expires_at_wall_clock = datetime.now(UTC) + timedelta(seconds=self._ttl_seconds)
            preview = Preview(
                preview_id=secrets.token_urlsafe(24),
                kind=kind,
                payload=dict(payload),
                summary=dict(summary),
                expires_at=now + self._ttl_seconds,
                expires_at_iso=expires_at_wall_clock.replace(microsecond=0).isoformat(),
            )
            self._entries[preview.preview_id] = preview
            return preview

    async def get(self, preview_id: str) -> Preview:
        async with self._lock:
            self._purge_expired()
            preview = self._entries.get(preview_id)
            if preview is None:
                raise TossInvestError(
                    "The preview does not exist or has expired",
                    code="preview-not-found",
                )
            return preview

    async def approve(self, preview_id: str) -> Preview:
        async with self._lock:
            self._purge_expired()
            preview = self._entries.get(preview_id)
            if preview is None:
                raise TossInvestError(
                    "The preview does not exist or has expired",
                    code="preview-not-found",
                )
            if preview.consumed:
                raise TossInvestError("The preview was already used", code="preview-already-used")
            preview.approved = True
            preview.approved_at = datetime.now(UTC).replace(microsecond=0).isoformat()
            return preview

    async def record_approval_failure(
        self,
        preview_id: str,
        *,
        max_attempts: int = 5,
    ) -> None:
        async with self._lock:
            self._purge_expired()
            preview = self._entries.get(preview_id)
            if preview is None:
                return
            preview.failed_approval_attempts += 1
            if preview.failed_approval_attempts >= max_attempts:
                self._entries.pop(preview_id, None)

    async def require_approved(
        self,
        preview_id: str,
        *,
        expected_kind: PreviewKind,
    ) -> Preview:
        async with self._lock:
            return self._validate_for_execution(preview_id, expected_kind)

    async def invalidate(self, preview_id: str) -> None:
        async with self._lock:
            self._entries.pop(preview_id, None)

    async def consume(
        self,
        preview_id: str,
        *,
        expected_kind: PreviewKind,
    ) -> Preview:
        async with self._lock:
            preview = self._validate_for_execution(preview_id, expected_kind)
            preview.consumed = True
            return preview

    def _validate_for_execution(
        self,
        preview_id: str,
        expected_kind: PreviewKind,
    ) -> Preview:
        self._purge_expired()
        preview = self._entries.get(preview_id)
        if preview is None:
            raise TossInvestError(
                "The preview does not exist or has expired",
                code="preview-not-found",
            )
        if preview.kind != expected_kind:
            raise TossInvestError("Preview type mismatch", code="preview-type-mismatch")
        if preview.consumed:
            raise TossInvestError("The preview was already used", code="preview-already-used")
        if not preview.approved:
            raise TossInvestError(
                "Human approval is required before executing this preview",
                code="approval-required",
            )
        return preview

    def _purge_expired(self) -> None:
        now = self._clock()
        self._entries = {
            key: value
            for key, value in self._entries.items()
            if value.expires_at > now and not value.consumed
        }
