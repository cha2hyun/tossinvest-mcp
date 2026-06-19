from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from ipaddress import ip_address
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

    tossinvest_client_id: str | None = Field(default=None, min_length=1)
    tossinvest_client_secret: SecretStr | None = Field(default=None, min_length=1)
    tossinvest_account_seq: str | None = Field(default=None, pattern=r"^\d+$")
    tossinvest_account_index: int | None = Field(default=None, ge=1, le=100)
    tossinvest_enable_trading: bool = False
    tossinvest_max_order_krw: Decimal | None = Field(default=None, gt=0)
    tossinvest_max_order_usd: Decimal | None = Field(default=None, gt=0)
    tossinvest_approval_token_sha256: SecretStr | None = None
    tossinvest_approval_base_url: str = "http://127.0.0.1:8000"
    tossinvest_base_url: str = "https://openapi.tossinvest.com"
    tossinvest_request_timeout: float = Field(default=15.0, gt=0, le=120)

    mcp_auth_token: SecretStr | None = Field(default=None, min_length=16)
    mcp_allowed_origins: OriginList = Field(default_factory=list)
    mcp_host: str = "0.0.0.0"  # noqa: S104 - container listens on all interfaces
    mcp_port: int = Field(default=8000, ge=1, le=65535)
    mcp_published_host: str = "127.0.0.1"
    mcp_tenant_cache_size: int = Field(default=100, ge=1, le=10000)
    mcp_tenant_cache_ttl: int = Field(default=3600, ge=120, le=86400)
    mcp_trusted_proxy_ips: str = Field(default="127.0.0.1", min_length=1)
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

    @field_validator("mcp_allowed_origins")
    @classmethod
    def validate_allowed_origins(cls, value: list[str]) -> list[str]:
        for origin in value:
            cls._validate_origin(
                origin,
                name="MCP_ALLOWED_ORIGINS",
                allow_loopback_http=True,
            )
        return value

    @field_validator("mcp_trusted_proxy_ips")
    @classmethod
    def validate_trusted_proxy_ips(cls, value: str) -> str:
        addresses = [item.strip() for item in value.split(",") if item.strip()]
        if not addresses or "*" in addresses:
            raise ValueError("MCP_TRUSTED_PROXY_IPS must list explicit proxy IP addresses")
        for address in addresses:
            try:
                ip_address(address)
            except ValueError as exc:
                raise ValueError("MCP_TRUSTED_PROXY_IPS must contain only IP addresses") from exc
        return ",".join(addresses)

    @field_validator("mcp_published_host")
    @classmethod
    def validate_published_host(cls, value: str) -> str:
        try:
            ip_address(value)
        except ValueError as exc:
            raise ValueError("MCP_PUBLISHED_HOST must be an IP address") from exc
        return value

    @model_validator(mode="after")
    def validate_trading_settings(self) -> Self:
        has_client_id = self.tossinvest_client_id is not None
        has_client_secret = self.tossinvest_client_secret is not None
        if has_client_id != has_client_secret:
            raise ValueError(
                "TOSSINVEST_CLIENT_ID and TOSSINVEST_CLIENT_SECRET must be configured together"
            )

        mcp_token = (
            self.mcp_auth_token.get_secret_value() if self.mcp_auth_token is not None else None
        )
        client_secret = (
            self.tossinvest_client_secret.get_secret_value()
            if self.tossinvest_client_secret is not None
            else None
        )
        if mcp_token is not None and client_secret is not None:
            if (
                hashlib.sha256(mcp_token.encode()).digest()
                == hashlib.sha256(client_secret.encode()).digest()
            ):
                raise ValueError("MCP_AUTH_TOKEN must be different from TOSSINVEST_CLIENT_SECRET")

        self._validate_origin(
            self.tossinvest_approval_base_url,
            name="TOSSINVEST_APPROVAL_BASE_URL",
            allow_loopback_http=True,
        )
        self._validate_origin(
            self.tossinvest_base_url,
            name="TOSSINVEST_BASE_URL",
            allow_loopback_http=True,
        )

        if self.tossinvest_enable_trading and has_client_id:
            missing = []
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
            assert client_secret is not None
            client_secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()
            if (
                mcp_token is not None
                and approval_hash == hashlib.sha256(mcp_token.encode()).hexdigest()
            ):
                raise ValueError("The human approval token must be different from MCP_AUTH_TOKEN")
            if approval_hash == client_secret_hash:
                raise ValueError(
                    "The human approval token must be different from TOSSINVEST_CLIENT_SECRET"
                )
        return self

    @staticmethod
    def _validate_origin(
        value: str,
        *,
        name: str,
        allow_loopback_http: bool,
    ) -> None:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(f"{name} must be an HTTP(S) origin")
        if parsed.path not in {"", "/"}:
            raise ValueError(f"{name} must not contain a path")
        loopback_hosts = {"127.0.0.1", "::1", "localhost"}
        if parsed.scheme == "http" and (
            not allow_loopback_http or parsed.hostname not in loopback_hosts
        ):
            raise ValueError(f"{name} must use HTTPS unless it is a loopback origin")

    @property
    def has_static_credentials(self) -> bool:
        return self.tossinvest_client_id is not None and self.tossinvest_client_secret is not None

    @classmethod
    def from_request_headers(
        cls,
        runtime: Settings,
        headers: dict[str, str],
    ) -> Settings:
        client_id = headers.get("x-tossinvest-client-id", "").strip()
        client_secret = headers.get("x-tossinvest-client-secret", "").strip()
        if not client_id or not client_secret:
            raise ValueError("X-Tossinvest-Client-Id and X-Tossinvest-Client-Secret are required")

        return cls(
            tossinvest_client_id=client_id,
            tossinvest_client_secret=SecretStr(client_secret),
            tossinvest_account_seq=(headers.get("x-tossinvest-account-seq", "").strip() or None),
            tossinvest_account_index=cls._optional_int_header(
                headers,
                "x-tossinvest-account-index",
            ),
            tossinvest_enable_trading=runtime.tossinvest_enable_trading,
            tossinvest_max_order_krw=cls._optional_decimal_header(
                headers,
                "x-tossinvest-max-order-krw",
            ),
            tossinvest_max_order_usd=cls._optional_decimal_header(
                headers,
                "x-tossinvest-max-order-usd",
            ),
            tossinvest_approval_token_sha256=(
                SecretStr(headers["x-tossinvest-approval-token-sha256"].strip())
                if headers.get("x-tossinvest-approval-token-sha256", "").strip()
                else None
            ),
            tossinvest_approval_base_url=runtime.tossinvest_approval_base_url,
            tossinvest_base_url=runtime.tossinvest_base_url,
            tossinvest_request_timeout=runtime.tossinvest_request_timeout,
            mcp_auth_token=None,
            mcp_allowed_origins=runtime.mcp_allowed_origins,
            mcp_host=runtime.mcp_host,
            mcp_port=runtime.mcp_port,
            mcp_published_host=runtime.mcp_published_host,
            mcp_tenant_cache_size=runtime.mcp_tenant_cache_size,
            mcp_tenant_cache_ttl=runtime.mcp_tenant_cache_ttl,
            mcp_trusted_proxy_ips=runtime.mcp_trusted_proxy_ips,
            log_level=runtime.log_level,
        )

    @staticmethod
    def _optional_decimal_header(headers: dict[str, str], name: str) -> Decimal | None:
        raw = headers.get(name, "").strip()
        if not raw:
            return None
        try:
            return Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"{name} must be a decimal number") from exc

    @staticmethod
    def _optional_int_header(headers: dict[str, str], name: str) -> int | None:
        raw = headers.get(name, "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
