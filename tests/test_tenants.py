from __future__ import annotations

import pytest

import tossinvest_mcp.tenants as tenants_module
from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.settings import Settings
from tossinvest_mcp.tenants import TenantServiceRegistry

from .test_service import StubClient


class TenantStubClient(StubClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings


@pytest.mark.asyncio
async def test_registry_builds_isolated_services_from_request_headers(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_headers = {
        "x-tossinvest-client-id": "client-a",
        "x-tossinvest-client-secret": "secret-a",
        "x-tossinvest-account-seq": "1",
    }
    monkeypatch.setattr(
        tenants_module,
        "get_http_headers",
        lambda **_: dict(current_headers),
    )
    monkeypatch.setattr(
        tenants_module,
        "TossInvestClient",
        TenantStubClient,
    )
    registry = TenantServiceRegistry(runtime_settings)

    service_a = await registry.current_service()
    service_a_again = await registry.current_service()
    current_headers.update(
        {
            "x-tossinvest-client-id": "client-b",
            "x-tossinvest-client-secret": "secret-b",
        }
    )
    service_b = await registry.current_service()

    assert service_a is service_a_again
    assert service_a is not service_b
    assert service_a.settings.tossinvest_client_id == "client-a"
    assert service_b.settings.tossinvest_client_id == "client-b"
    await registry.close()


@pytest.mark.asyncio
async def test_registry_rejects_missing_request_credentials(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tenants_module, "get_http_headers", lambda **_: {})
    registry = TenantServiceRegistry(runtime_settings)

    with pytest.raises(TossInvestError) as exc_info:
        await registry.current_service()

    assert exc_info.value.code == "credentials-required"
    assert "X-Tossinvest-Client-Id" in exc_info.value.data["required_headers"]


@pytest.mark.asyncio
async def test_trading_registry_reports_all_required_private_headers(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = runtime_settings.model_dump()
    values["tossinvest_enable_trading"] = True
    runtime = Settings(**values)
    monkeypatch.setattr(tenants_module, "get_http_headers", lambda **_: {})
    registry = TenantServiceRegistry(runtime)

    with pytest.raises(TossInvestError) as exc_info:
        await registry.current_service()

    assert set(exc_info.value.data["required_headers"]) == {
        "X-Tossinvest-Client-Id",
        "X-Tossinvest-Client-Secret",
        "X-Tossinvest-Max-Order-Krw",
        "X-Tossinvest-Max-Order-Usd",
        "X-Tossinvest-Approval-Token-Sha256",
    }
    assert exc_info.value.data["optional_headers"] == ["X-Tossinvest-Account-Index"]


def test_request_headers_build_tenant_settings(runtime_settings: Settings) -> None:
    tenant = Settings.from_request_headers(
        runtime_settings,
        {
            "x-tossinvest-client-id": "client",
            "x-tossinvest-client-secret": "secret",
            "x-tossinvest-account-index": "2",
        },
    )

    assert tenant.tossinvest_client_id == "client"
    assert tenant.tossinvest_client_secret is not None
    assert tenant.tossinvest_client_secret.get_secret_value() == "secret"
    assert tenant.tossinvest_account_seq is None
    assert tenant.tossinvest_account_index == 2
    assert tenant.mcp_auth_token is None


@pytest.mark.asyncio
async def test_invalid_private_header_value_is_not_reflected(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leaked_value = "not-a-valid-account-secret-value"
    monkeypatch.setattr(
        tenants_module,
        "get_http_headers",
        lambda **_: {
            "x-tossinvest-client-id": "client",
            "x-tossinvest-client-secret": "secret",
            "x-tossinvest-account-seq": leaked_value,
        },
    )
    registry = TenantServiceRegistry(runtime_settings)

    with pytest.raises(TossInvestError) as exc_info:
        await registry.current_service()

    assert leaked_value not in str(exc_info.value)
    assert leaked_value not in str(exc_info.value.as_dict())
