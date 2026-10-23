# Security Policy

## Supported versions

Only the latest published [GitHub Release](https://github.com/cha2hyun/tossinvest-mcp/releases/latest)
receives security fixes. Older releases, untagged commits from `main`, and locally modified builds
are not supported versions. When reporting an issue, include the exact release tag or image digest.

## Reporting

Do not open a public issue for credential exposure, authentication bypass, order-safety bypass, or
unexpected live-order execution. Report privately to `cha2hyun.dev@gmail.com` with the affected
version, deployment mode, impact, sanitized request IDs, and minimal reproduction steps.

Never include real Toss credentials, request headers, account values, access tokens, or approval
tokens.

## Threat model

The host, container runtime, reverse proxy, and administrator are trusted. The MCP client or model
may make incorrect or adversarial tool choices. Upstream state can change between preview and
execution, and a network failure can leave a dispatched order in an unknown state.

The server cannot protect in-memory credentials from a host administrator, Docker daemon access,
kernel compromise, arbitrary process inspection, or code execution inside the server process.

## Credential boundary

- The server `.env` and container environment must not contain Toss client credentials or account
  sequence values.
- The MCP client sends credentials as private `X-Tossinvest-*` request headers.
- Request headers are not MCP tool arguments, resources, prompts, or schemas.
- OAuth tokens, refresh locks, and rate limits are shared only when the upstream base URL,
  client ID, and client secret match. The lookup uses a one-way credential fingerprint.
- Account selection, order limits, approval hashes, HTTP clients, and previews remain isolated
  per tenant configuration. Authentication state is removed when no cached tenant or pending
  admission refers to it.
- New tenants authenticate before replacing cached contexts. Concurrent admissions are bounded
  by `MCP_TENANT_CACHE_SIZE`; active requests and unexpired, unused previews prevent eviction.
- Credential and account fields are redacted from normalized upstream responses and errors.
- The original human approval token remains outside both server and MCP client configuration. Only
  its SHA-256 digest is sent in trading-mode headers.

Do not grant the model shell, filesystem, Docker, proxy administration, secret-manager, packet
capture, or process-inspection access to this credential boundary.

## HTTPS and logging requirements

- Public plain HTTP is forbidden. The application returns `426 https-required` unless the peer and
  requested host are both loopback.
- The supplied Compose file explicitly sets `MCP_TRUST_LOOPBACK_PUBLISH=true` to support local
  connections arriving through a Docker gateway. This exception requires both
  `MCP_PUBLISHED_HOST` and the requested host to be loopback, and trusts Docker to enforce the
  configured loopback host-port binding. It does not verify that binding itself. Keep this option
  disabled for direct execution or any deployment that cannot guarantee that binding; the default
  outside the supplied Compose file is `false`. A public `MCP_PUBLISHED_HOST` disables the exception.
- Public deployments must terminate TLS at a trusted reverse proxy and preserve the original
  request scheme for Uvicorn.
- Put only trusted reverse-proxy addresses in `MCP_TRUSTED_PROXY_IPS`; never trust forwarded
  headers from arbitrary clients.
- Redact or drop `X-Tossinvest-*`, `Authorization`, cookies, form bodies, and request/response body
  dumps from reverse-proxy, gateway, WAF, APM, and exception logs.
- Uvicorn access logs are disabled by default.
- Responses use `Cache-Control: no-store`; HTTPS responses use HSTS.
- Restrict `/healthz`, `/readyz`, and `/approvals/*` externally.

## Outbound TLS trust

The October 2026 [eMudhra CA incident](https://emudhra.we-have-a-problem.com/) affects both
direct emSign chains and AAA cross-signed chains. The lockfile uses patched certifi, CI uses
uv 0.13.5, and the Docker image requires Debian's fixed CA bundle and pip 26.2.2 or later.
FastMCP 4 uses system trust, so upgrading certifi alone does not repair every TLS client.

Rebuild existing images with `docker compose build --pull --no-cache` and recreate containers
after reviewing the new image. An existing running container keeps its previous trust stores.
For direct host execution, also update the operating system trust store and every installer or
custom CA bundle in use. Do not disable certificate verification or assume a network timeout
proves that a compromised certificate is rejected.

Verify both incident test chains fail with a certificate verification error in the actual runtime,
while ordinary HTTPS requests to `https://openapi.tossinvest.com` still complete TLS successfully.
The incident page provides test hosts and offline certificate chains.

## Order invariants

- Trading tools do not exist without `--dangerously-enable-trading`.
- Every write requires an unexpired, externally approved, single-use preview.
- Price, exchange rate, availability, order state, and configured limits are revalidated before
  dispatch.
- Writes are never retried after token expiry, rate limits, timeout, network failure, or upstream
  errors.
- `order-state-unknown` requires order-history inspection before any further write.
- Orders must not be split to evade configured or hard limits.

## Incident response

1. Stop the MCP server and block public access.
2. Revoke or rotate the Toss API client credentials.
3. Replace the human approval token and its digest.
4. Inspect Toss order history through a trusted interface.
5. Purge or secure proxy, gateway, APM, and application logs containing leaked values.
6. Review host, Docker, reverse-proxy, and MCP-client access.
