from __future__ import annotations

import asyncio

import pytest

import tossinvest_mcp.tenants as tenants_module
from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.previews import PreviewStore
from tossinvest_mcp.settings import Settings
from tossinvest_mcp.tenants import TenantServiceRegistry

from .test_service import StubClient


class TenantStubClient(StubClient):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self.close_calls = 0

    async def aclose(self) -> None:
        self.close_calls += 1


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

    async with registry.current_service() as service_a:
        async with registry.current_service() as service_a_again:
            assert service_a is service_a_again
        current_headers.update(
            {
                "x-tossinvest-client-id": "client-b",
                "x-tossinvest-client-secret": "secret-b",
            }
        )
        async with registry.current_service() as service_b:
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
        async with registry.current_service():
            pytest.fail("Missing credentials were accepted")

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
        async with registry.current_service():
            pytest.fail("Missing trading credentials were accepted")

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
        async with registry.current_service():
            pytest.fail("Invalid headers were accepted")

    assert leaked_value not in str(exc_info.value)
    assert leaked_value not in str(exc_info.value.as_dict())


@pytest.mark.asyncio
async def test_busy_tenant_is_not_evicted_at_capacity_or_after_ttl(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    headers = {"x-tossinvest-client-id": "alpha", "x-tossinvest-client-secret": "secret-alpha"}
    monkeypatch.setattr(tenants_module, "get_http_headers", lambda **_: dict(headers))
    monkeypatch.setattr(tenants_module, "TossInvestClient", TenantStubClient)
    runtime = runtime_settings.model_copy(update={"mcp_tenant_cache_size": 1})
    registry = TenantServiceRegistry(runtime, clock=lambda: now)

    async with registry.current_service() as alpha:
        assert isinstance(alpha.client, TenantStubClient)
        now = runtime.mcp_tenant_cache_ttl + 1
        headers["x-tossinvest-client-id"] = "beta"
        with pytest.raises(TossInvestError) as exc_info:
            async with registry.current_service():
                pytest.fail("Busy tenant was evicted")
        assert exc_info.value.code == "tenant-capacity-exceeded"
        assert alpha.client.close_calls == 0

    headers["x-tossinvest-client-id"] = "alpha"
    async with registry.current_service() as reused:
        assert reused is alpha
    headers["x-tossinvest-client-id"] = "beta"
    async with registry.current_service() as beta:
        assert beta is not alpha
        assert alpha.client.close_calls == 1
    await registry.close()


@pytest.mark.asyncio
async def test_cancelled_request_releases_tenant_and_shutdown_waits_for_active_users(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tenants_module,
        "get_http_headers",
        lambda **_: {"x-tossinvest-client-id": "alpha", "x-tossinvest-client-secret": "secret"},
    )
    monkeypatch.setattr(tenants_module, "TossInvestClient", TenantStubClient)
    registry = TenantServiceRegistry(runtime_settings)
    started = asyncio.Event()

    async def request() -> None:
        async with registry.current_service():
            started.set()
            await asyncio.Event().wait()

    async with registry.current_service() as service:
        task = asyncio.create_task(request())
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await registry.close()
        assert isinstance(service.client, TenantStubClient)
        assert service.client.close_calls == 0
    assert service.client.close_calls == 1
    await registry.close()
    assert service.client.close_calls == 1


@pytest.mark.asyncio
async def test_idle_tenant_expires_and_preview_ownership_is_removed(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    monkeypatch.setattr(
        tenants_module,
        "get_http_headers",
        lambda **_: {"x-tossinvest-client-id": "alpha", "x-tossinvest-client-secret": "secret"},
    )
    monkeypatch.setattr(tenants_module, "TossInvestClient", TenantStubClient)
    registry = TenantServiceRegistry(runtime_settings, clock=lambda: now)
    async with registry.current_service() as service:
        service.previews = PreviewStore(clock=lambda: now)
        preview = await service.previews.create("cancel", {}, {})
        await registry.register_preview(preview.preview_id, service)
    async with registry.service_for_preview(preview.preview_id) as owner:
        assert owner is service

    now = 121.0
    with pytest.raises(TossInvestError) as exc_info:
        async with registry.service_for_preview(preview.preview_id):
            pytest.fail("Expired preview resolved")
    assert exc_info.value.code == "preview-not-found"
    assert not registry._preview_owners

    now += runtime_settings.mcp_tenant_cache_ttl
    async with registry.current_service() as replacement:
        assert replacement is not service
        assert isinstance(service.client, TenantStubClient)
        assert service.client.close_calls == 1
    await registry.close()
