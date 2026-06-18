from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SENSITIVE_KEYS = {
    "access_token",
    "approval_token",
    "authorization",
    "client_secret",
    "mcp_auth_token",
    "refresh_token",
    "tossinvest_approval_token_sha256",
    "tossinvest_client_secret",
    "x-tossinvest-account",
}


def mask_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}***{value[-4:]}"


def sanitize_for_log(value: Any) -> Any:
    """Recursively mask credentials and account identifiers before logging."""

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            sanitized[str(key)] = (
                mask_secret(str(item)) if lowered in SENSITIVE_KEYS else sanitize_for_log(item)
            )
        return sanitized
    if isinstance(value, list):
        return [sanitize_for_log(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_for_log(item) for item in value)
    return value
