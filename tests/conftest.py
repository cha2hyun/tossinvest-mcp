from __future__ import annotations

import hashlib
from decimal import Decimal

import pytest
from pydantic import SecretStr

from tossinvest_mcp.settings import Settings

APPROVAL_TOKEN = "human-approval-token-123456789"  # noqa: S105 - test-only value
APPROVAL_TOKEN_SHA256 = hashlib.sha256(APPROVAL_TOKEN.encode()).hexdigest()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        tossinvest_client_id="client-id",
        tossinvest_client_secret=SecretStr("client-secret"),
        tossinvest_account_seq="1",
        tossinvest_base_url="https://openapi.test",
        mcp_auth_token=SecretStr("mcp-test-token-1234"),
    )


@pytest.fixture
def trading_settings() -> Settings:
    return Settings(
        tossinvest_client_id="client-id",
        tossinvest_client_secret=SecretStr("client-secret"),
        tossinvest_account_seq="1",
        tossinvest_enable_trading=True,
        tossinvest_max_order_krw=Decimal("10000000"),
        tossinvest_max_order_usd=Decimal("10000"),
        tossinvest_approval_token_sha256=SecretStr(APPROVAL_TOKEN_SHA256),
        tossinvest_approval_base_url="http://127.0.0.1:8000",
        tossinvest_base_url="https://openapi.test",
        mcp_auth_token=SecretStr("mcp-test-token-1234"),
    )
