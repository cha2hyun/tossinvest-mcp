from __future__ import annotations

import asyncio
from contextvars import ContextVar
from urllib.parse import parse_qs

import httpx
import pytest

import tossinvest_mcp.tenants as tenants_module
from tossinvest_mcp.client import ClientAuthState, TossInvestClient
from tossinvest_mcp.errors import TossInvestError
from tossinvest_mcp.previews import PreviewStore
from tossinvest_mcp.service import TossInvestService
from tossinvest_mcp.settings import Settings
from tossinvest_mcp.tenants import TenantServiceRegistry

from .test_service import StubClient


class TenantStubClient(StubClient):
    def __init__(self, settings: Settings, *, auth_state: ClientAuthState | None = None) -> None:
        super().__init__()
        self.settings = settings
        self.auth_state = auth_state
        self.close_calls = 0

    async def authenticate(self) -> None:
        return None

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


@pytest.mark.asyncio
async def test_account_contexts_share_oauth_without_sharing_accounts_or_previews(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers: ContextVar[dict[str, str]] = ContextVar("headers")
    monkeypatch.setattr(tenants_module, "get_http_headers", lambda **_: headers.get())
    token_calls = 0
    current_token = ""
    account_headers: list[str] = []
    clients: list[TossInvestClient] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls, current_token
        if request.url.path == "/oauth2/token":
            token_calls += 1
            current_token = f"test-token-{token_calls}"
            await asyncio.sleep(0)
            return httpx.Response(200, json={"access_token": current_token, "expires_in": 3600})
        if request.headers["Authorization"] != f"Bearer {current_token}":
            return httpx.Response(401, json={"error": {"code": "token-revoked"}})
        account_headers.append(request.headers["X-Tossinvest-Account"])
        return httpx.Response(200, json={"result": {"ok": True}})

    async with httpx.AsyncClient(
        base_url="https://openapi.test", transport=httpx.MockTransport(handler)
    ) as http:

        def make_client(settings: Settings, *, auth_state: ClientAuthState) -> TossInvestClient:
            client = TossInvestClient(settings, http_client=http, auth_state=auth_state)
            clients.append(client)
            return client

        monkeypatch.setattr(tenants_module, "TossInvestClient", make_client)
        registry = TenantServiceRegistry(runtime_settings)

        async def request(account: str) -> TossInvestService:
            headers.set(
                {
                    "x-tossinvest-client-id": "one-client",
                    "x-tossinvest-client-secret": "one-secret",
                    "x-tossinvest-account-seq": account,
                }
            )
            async with registry.current_service() as service:
                await service.client.request(
                    "GET", "/api/v1/holdings", group="ASSET", account_required=True
                )
                return service

        alpha, beta = await asyncio.gather(request("1"), request("2"))
        assert alpha is not beta
        assert alpha.previews is not beta.previews
        preview = await alpha.previews.create("cancel", {}, {})
        with pytest.raises(TossInvestError, match="does not exist"):
            await beta.previews.get(preview.preview_id)
        # A write in the second account must retain a valid token after the
        # first account performs another read; writes are never retried.
        await alpha.client.request("GET", "/api/v1/holdings", group="ASSET", account_required=True)
        await beta.client.request(
            "POST", "/api/v1/orders", group="ORDER", account_required=True, write_operation=True
        )
        assert token_calls == 1
        assert sorted(account_headers) == ["1", "1", "2", "2"]
        assert clients[0]._rate_limiter is clients[1]._rate_limiter
        await registry.close()
        assert not registry._auth_entries


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_header", ["x-tossinvest-client-id", "x-tossinvest-client-secret"])
async def test_failed_authentication_does_not_evict_an_existing_tenant(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    invalid_header: str,
) -> None:
    headers = {"x-tossinvest-client-id": "valid", "x-tossinvest-client-secret": "test-secret"}
    monkeypatch.setattr(tenants_module, "get_http_headers", lambda **_: dict(headers))
    token_calls = 0

    class TrackingClient(TossInvestClient):
        close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1
            await super().aclose()

    created: list[TrackingClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_calls
        assert request.url.path == "/oauth2/token"
        token_calls += 1
        form = parse_qs(request.content.decode())
        if form["client_id"] == ["valid"] and form["client_secret"] == ["test-secret"]:
            return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600})
        return httpx.Response(401, json={"error": "invalid_client"})

    async with httpx.AsyncClient(
        base_url="https://openapi.test", transport=httpx.MockTransport(handler)
    ) as http:

        def make_client(settings: Settings, *, auth_state: ClientAuthState) -> TrackingClient:
            client = TrackingClient(settings, http_client=http, auth_state=auth_state)
            created.append(client)
            return client

        monkeypatch.setattr(tenants_module, "TossInvestClient", make_client)
        registry = TenantServiceRegistry(
            runtime_settings.model_copy(update={"mcp_tenant_cache_size": 1})
        )
        async with registry.current_service() as original:
            pass
        valid_value = headers[invalid_header]
        headers[invalid_header] = "invalid"
        with pytest.raises(TossInvestError) as exc_info:
            async with registry.current_service():
                pytest.fail("Unauthenticated tenant admitted")
        assert exc_info.value.status_code == 401
        headers[invalid_header] = valid_value
        async with registry.current_service() as reused:
            assert reused is original
        assert token_calls == 2
        assert created[0].close_calls == 0
        assert created[1].close_calls == 1
        assert len(registry._entries) == len(registry._auth_entries) == 1
        assert not registry._pending
        await registry.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("approved", [False, True])
async def test_live_previews_survive_cache_pressure_until_expiry(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    approved: bool,
) -> None:
    now = 0.0
    headers = {"x-tossinvest-client-id": "alpha", "x-tossinvest-client-secret": "test-secret"}
    monkeypatch.setattr(tenants_module, "get_http_headers", lambda **_: dict(headers))
    monkeypatch.setattr(tenants_module, "TossInvestClient", TenantStubClient)
    registry = TenantServiceRegistry(
        runtime_settings.model_copy(update={"mcp_tenant_cache_size": 1}), clock=lambda: now
    )
    async with registry.current_service() as alpha:
        alpha.previews = PreviewStore(clock=lambda: now)
        preview = await alpha.previews.create("cancel", {}, {})
        if approved:
            await alpha.previews.approve(preview.preview_id)
        await registry.register_preview(preview.preview_id, alpha)
    headers["x-tossinvest-client-id"] = "beta"
    with pytest.raises(TossInvestError) as exc_info:
        async with registry.current_service():
            pytest.fail("Live preview was evicted")
    assert exc_info.value.code == "tenant-capacity-exceeded"
    async with registry.service_for_preview(preview.preview_id) as owner:
        assert owner is alpha
        assert (await owner.previews.get(preview.preview_id)).approved is approved

    now = 121.0
    async with registry.current_service() as beta:
        assert beta is not alpha
    assert isinstance(alpha.client, TenantStubClient)
    assert alpha.client.close_calls == 1
    assert len(registry._auth_entries) == 1
    await registry.close()


@pytest.mark.asyncio
async def test_pending_admissions_are_bounded_and_cancellation_releases_resources(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"x-tossinvest-client-id": "alpha", "x-tossinvest-client-secret": "test-secret"}
    monkeypatch.setattr(tenants_module, "get_http_headers", lambda **_: dict(headers))
    started = asyncio.Event()
    finish = asyncio.Event()
    created: list[TenantStubClient] = []

    class SlowAuthClient(TenantStubClient):
        async def authenticate(self) -> None:
            if self.settings.tossinvest_client_id == "beta":
                started.set()
                await finish.wait()

    def make_client(settings: Settings, *, auth_state: ClientAuthState) -> TenantStubClient:
        client = SlowAuthClient(settings, auth_state=auth_state)
        created.append(client)
        return client

    monkeypatch.setattr(tenants_module, "TossInvestClient", make_client)
    registry = TenantServiceRegistry(
        runtime_settings.model_copy(update={"mcp_tenant_cache_size": 1})
    )
    async with registry.current_service() as alpha:
        pass

    async def acquire() -> None:
        async with registry.current_service():
            pass

    headers["x-tossinvest-client-id"] = "beta"
    task = asyncio.create_task(acquire())
    await asyncio.wait_for(started.wait(), timeout=2)
    headers["x-tossinvest-client-id"] = "gamma"
    with pytest.raises(TossInvestError) as exc_info:
        await acquire()
    assert exc_info.value.code == "tenant-capacity-exceeded"
    headers["x-tossinvest-client-id"] = "alpha"
    async with asyncio.timeout(2), registry.current_service() as reused:
        assert reused is alpha
    assert len(created) == 2
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert created[1].close_calls == 1
    assert not registry._pending
    assert len(registry._auth_entries) == 1
    headers["x-tossinvest-client-id"] = "gamma"
    await acquire()
    await registry.close()
    assert not registry._auth_entries


@pytest.mark.asyncio
async def test_shutdown_rejects_an_inflight_admission_and_wakes_its_waiters(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tenants_module,
        "get_http_headers",
        lambda **_: {
            "x-tossinvest-client-id": "test-id",
            "x-tossinvest-client-secret": "test-secret",
        },
    )
    started = asyncio.Event()
    finish = asyncio.Event()
    created: list[TenantStubClient] = []

    class SlowAuthClient(TenantStubClient):
        async def authenticate(self) -> None:
            started.set()
            await finish.wait()

    def make_client(settings: Settings, *, auth_state: ClientAuthState) -> TenantStubClient:
        client = SlowAuthClient(settings, auth_state=auth_state)
        created.append(client)
        return client

    monkeypatch.setattr(tenants_module, "TossInvestClient", make_client)
    registry = TenantServiceRegistry(runtime_settings)

    async def acquire() -> None:
        async with registry.current_service():
            pytest.fail("Admission completed after shutdown")

    first = asyncio.create_task(acquire())
    await asyncio.wait_for(started.wait(), timeout=2)
    second = asyncio.create_task(acquire())
    await asyncio.sleep(0)
    await registry.close()
    with pytest.raises(TossInvestError, match="shutting down"):
        await asyncio.wait_for(second, timeout=2)
    finish.set()
    with pytest.raises(TossInvestError, match="shutting down"):
        await asyncio.wait_for(first, timeout=2)
    assert len(created) == 1
    assert created[0].close_calls == 1
    assert not registry._entries
    assert not registry._auth_entries
    assert not registry._pending


@pytest.mark.asyncio
@pytest.mark.parametrize("error_code", ["oauth-network-error", "upstream-error"])
async def test_concurrent_failed_admissions_share_one_authentication_attempt(
    runtime_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
) -> None:
    monkeypatch.setattr(
        tenants_module,
        "get_http_headers",
        lambda **_: {
            "x-tossinvest-client-id": "test-id",
            "x-tossinvest-client-secret": "test-secret",
        },
    )
    started = asyncio.Event()
    finish = asyncio.Event()
    attempts = 0
    created: list[TenantStubClient] = []

    class FailingAuthClient(TenantStubClient):
        async def authenticate(self) -> None:
            nonlocal attempts
            attempts += 1
            started.set()
            await finish.wait()
            raise TossInvestError("Credential verification failed", code=error_code)

    def make_client(settings: Settings, *, auth_state: ClientAuthState) -> TenantStubClient:
        client = FailingAuthClient(settings, auth_state=auth_state)
        created.append(client)
        return client

    monkeypatch.setattr(tenants_module, "TossInvestClient", make_client)
    registry = TenantServiceRegistry(runtime_settings)

    async def acquire() -> None:
        async with registry.current_service():
            pytest.fail("Failed credentials admitted")

    first = asyncio.create_task(acquire())
    await asyncio.wait_for(started.wait(), timeout=2)
    followers = [asyncio.create_task(acquire()) for _ in range(4)]
    await asyncio.sleep(0)
    finish.set()
    results = await asyncio.wait_for(
        asyncio.gather(first, *followers, return_exceptions=True), timeout=2
    )
    assert attempts == len(created) == 1
    for result in results:
        assert isinstance(result, TossInvestError)
        assert result.code == error_code
        assert str(result) == "Credential verification failed"
    assert created[0].close_calls == 1
    assert not registry._entries
    assert not registry._auth_entries
    assert not registry._pending
    await registry.close()
