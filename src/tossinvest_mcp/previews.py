from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from tossinvest_mcp.errors import TossInvestError

PreviewKind = Literal["create", "modify", "cancel"]


@dataclass
class Preview:
    preview_id: str
    kind: PreviewKind
    payload: dict[str, Any]
    confirmation_phrase: str
    expires_at: float
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
        confirmation_phrase: str,
    ) -> Preview:
        async with self._lock:
            self._purge_expired()
            preview = Preview(
                preview_id=secrets.token_urlsafe(24),
                kind=kind,
                payload=dict(payload),
                confirmation_phrase=confirmation_phrase,
                expires_at=self._clock() + self._ttl_seconds,
            )
            self._entries[preview.preview_id] = preview
            return preview

    async def consume(
        self,
        preview_id: str,
        confirmation_phrase: str,
        *,
        expected_kind: PreviewKind,
    ) -> Preview:
        async with self._lock:
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
            if not secrets.compare_digest(preview.confirmation_phrase, confirmation_phrase):
                raise TossInvestError(
                    "The confirmation phrase does not match",
                    code="confirmation-mismatch",
                )
            preview.consumed = True
            return preview

    def _purge_expired(self) -> None:
        now = self._clock()
        self._entries = {
            key: value
            for key, value in self._entries.items()
            if value.expires_at > now and not value.consumed
        }
