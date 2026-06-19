from __future__ import annotations

from collections.abc import Mapping
from typing import Any

ACCOUNT_KEYS = {
    "accountno",
    "accountnumber",
    "accountseq",
    "x-tossinvest-account",
    "x-tossinvest-account-seq",
}

CREDENTIAL_KEYS = {
    "access_token",
    "accesstoken",
    "approvaltoken",
    "approval_token",
    "authorization",
    "clientid",
    "client_id",
    "clientsecret",
    "client_secret",
    "mcp_auth_token",
    "refresh_token",
    "refreshtoken",
    "tossinvest_approval_token_sha256",
    "tossinvest_client_id",
    "tossinvest_client_secret",
    "x-tossinvest-approval-token-sha256",
    "x-tossinvest-client-id",
    "x-tossinvest-client-secret",
}

SENSITIVE_KEYS = ACCOUNT_KEYS | CREDENTIAL_KEYS


def mask_secret(value: str) -> str:
    del value
    return "[REDACTED]"


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


def redact_sensitive_values(
    value: Any,
    secrets: tuple[str, ...] = (),
    *,
    redact_accounts: bool = True,
) -> Any:
    """Remove credential values from upstream data before it reaches tools or errors."""

    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            redacted[str(key)] = (
                "[REDACTED]"
                if lowered in CREDENTIAL_KEYS or (redact_accounts and lowered in ACCOUNT_KEYS)
                else redact_sensitive_values(
                    item,
                    secrets,
                    redact_accounts=redact_accounts,
                )
            )
        return redacted
    if isinstance(value, list):
        return [
            redact_sensitive_values(
                item,
                secrets,
                redact_accounts=redact_accounts,
            )
            for item in value
        ]
    if isinstance(value, tuple):
        return tuple(
            redact_sensitive_values(
                item,
                secrets,
                redact_accounts=redact_accounts,
            )
            for item in value
        )
    if isinstance(value, str):
        redacted_text = value
        for secret in secrets:
            if secret:
                redacted_text = redacted_text.replace(secret, "[REDACTED]")
        return redacted_text
    return value
