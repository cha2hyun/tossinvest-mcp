from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import SecretStr

from tossinvest_mcp.settings import Settings


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
        tossinvest_base_url="https://openapi.test",
        mcp_auth_token=SecretStr("mcp-test-token-1234"),
    )
