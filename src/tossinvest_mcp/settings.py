from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from typing import Annotated, Self
from urllib.parse import urlsplit

from pydantic import BeforeValidator, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_origins(value: object) -> object:
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


OriginList = Annotated[list[str], NoDecode, BeforeValidator(_split_origins)]


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        case_sensitive=False,
        extra="ignore",
    )

    tossinvest_client_id: str = Field(min_length=1)
    tossinvest_client_secret: SecretStr = Field(min_length=1)
    tossinvest_account_seq: str | None = Field(default=None, pattern=r"^\d+$")
    tossinvest_enable_trading: bool = False
    tossinvest_max_order_krw: Decimal | None = Field(default=None, gt=0)
    tossinvest_max_order_usd: Decimal | None = Field(default=None, gt=0)
    tossinvest_approval_token_sha256: SecretStr | None = None
    tossinvest_approval_base_url: str = "http://127.0.0.1:8000"
    tossinvest_base_url: str = "https://openapi.tossinvest.com"
    tossinvest_request_timeout: float = Field(default=15.0, gt=0, le=120)

    mcp_auth_token: SecretStr = Field(min_length=16)
    mcp_allowed_origins: OriginList = Field(default_factory=list)
    mcp_host: str = "0.0.0.0"  # noqa: S104 - container listens on all interfaces
    mcp_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    @field_validator("tossinvest_approval_token_sha256")
    @classmethod
    def validate_approval_token_hash(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value()
        if re.fullmatch(r"[0-9a-fA-F]{64}", raw) is None:
            raise ValueError("TOSSINVEST_APPROVAL_TOKEN_SHA256 must be a SHA-256 hex digest")
        return SecretStr(raw.lower())

    @model_validator(mode="after")
    def validate_trading_settings(self) -> Self:
        mcp_token = self.mcp_auth_token.get_secret_value()
        client_secret = self.tossinvest_client_secret.get_secret_value()
        if (
            hashlib.sha256(mcp_token.encode()).digest()
            == hashlib.sha256(client_secret.encode()).digest()
        ):
            raise ValueError("MCP_AUTH_TOKEN must be different from TOSSINVEST_CLIENT_SECRET")

        approval_url = urlsplit(self.tossinvest_approval_base_url)
        if (
            approval_url.scheme not in {"http", "https"}
            or not approval_url.hostname
            or approval_url.username is not None
            or approval_url.password is not None
            or approval_url.query
            or approval_url.fragment
        ):
            raise ValueError("TOSSINVEST_APPROVAL_BASE_URL must be an HTTP(S) origin")
        if approval_url.path not in {"", "/"}:
            raise ValueError("TOSSINVEST_APPROVAL_BASE_URL must not contain a path")
        if approval_url.scheme == "http" and approval_url.hostname not in {
            "127.0.0.1",
            "::1",
            "localhost",
        }:
            raise ValueError(
                "TOSSINVEST_APPROVAL_BASE_URL must use HTTPS unless it is a loopback origin"
            )

        if self.tossinvest_enable_trading:
            missing = []
            if not self.tossinvest_account_seq:
                missing.append("TOSSINVEST_ACCOUNT_SEQ")
            if self.tossinvest_max_order_krw is None:
                missing.append("TOSSINVEST_MAX_ORDER_KRW")
            if self.tossinvest_max_order_usd is None:
                missing.append("TOSSINVEST_MAX_ORDER_USD")
            if self.tossinvest_approval_token_sha256 is None:
                missing.append("TOSSINVEST_APPROVAL_TOKEN_SHA256")
            if missing:
                joined = ", ".join(missing)
                raise ValueError(f"Trading is enabled but required settings are missing: {joined}")
            assert self.tossinvest_approval_token_sha256 is not None
            approval_hash = self.tossinvest_approval_token_sha256.get_secret_value().lower()
            mcp_token_hash = hashlib.sha256(mcp_token.encode()).hexdigest()
            client_secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()
            if approval_hash == mcp_token_hash:
                raise ValueError("The human approval token must be different from MCP_AUTH_TOKEN")
            if approval_hash == client_secret_hash:
                raise ValueError(
                    "The human approval token must be different from TOSSINVEST_CLIENT_SECRET"
                )
        return self
