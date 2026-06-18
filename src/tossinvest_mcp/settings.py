from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, SecretStr, model_validator
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
    tossinvest_base_url: str = "https://openapi.tossinvest.com"
    tossinvest_request_timeout: float = Field(default=15.0, gt=0, le=120)

    mcp_auth_token: SecretStr = Field(min_length=16)
    mcp_allowed_origins: OriginList = Field(default_factory=list)
    mcp_host: str = "0.0.0.0"  # noqa: S104 - container listens on all interfaces
    mcp_port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    @model_validator(mode="after")
    def validate_trading_settings(self) -> Self:
        if self.tossinvest_enable_trading:
            missing = []
            if not self.tossinvest_account_seq:
                missing.append("TOSSINVEST_ACCOUNT_SEQ")
            if self.tossinvest_max_order_krw is None:
                missing.append("TOSSINVEST_MAX_ORDER_KRW")
            if self.tossinvest_max_order_usd is None:
                missing.append("TOSSINVEST_MAX_ORDER_USD")
            if missing:
                joined = ", ".join(missing)
                raise ValueError(f"Trading is enabled but required settings are missing: {joined}")
        return self
