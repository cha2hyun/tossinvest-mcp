# Security Policy

## Supported versions

Security fixes are provided for the latest released minor version. Users should pin a reviewed
SemVer container tag and update after reviewing release notes instead of relying indefinitely on
`latest`.

## Reporting a vulnerability

Do not open a public issue for credential exposure, authentication bypass, order-safety bypass,
unexpected live-order execution, or another exploitable vulnerability.

Report privately to `cha2hyun.dev@gmail.com` with:

- affected version or commit
- deployment mode
- impact and prerequisites
- minimal reproduction steps
- relevant request IDs with credentials removed

Do not include real Toss credentials, MCP tokens, approval tokens, account numbers, or access
tokens. The project will acknowledge reports when possible, investigate impact, and coordinate a
fix and disclosure appropriate to the risk.

## Threat model

The server assumes:

- the host, container runtime, and administrator are trusted
- the MCP client or agent may make incorrect or adversarial tool choices
- upstream market and account data may change between preview and execution
- network failures may leave a dispatched order in an unknown state
- browser requests may be cross-origin or automated

The server does not protect secrets from a host administrator, a user with Docker daemon access,
kernel compromise, or arbitrary code execution inside the server process. Those actors can inspect
process environment or memory.

## Credential boundaries

- The server process necessarily uses the Toss client secret and MCP authentication token.
- MCP tools, resources, prompts, schemas, errors, and normalized responses must not expose those
  values.
- `MCP_AUTH_TOKEN` must differ from `TOSSINVEST_CLIENT_SECRET`.
- The human approval token must differ from both and remain outside server and Hermes
  configuration.
- The server stores only `TOSSINVEST_APPROVAL_TOKEN_SHA256`, never the original approval token.
- Do not grant an agent shell, filesystem, Docker, secret-manager, or process-inspection access to
  the server's credential boundary.

## Deployment requirements

- Keep the published port bound to `127.0.0.1` unless an authenticated HTTPS reverse proxy and
  network access controls protect it.
- Use a secret manager or a private, permission-restricted `.env`.
- Use unpredictable credentials and rotate any value that may have leaked.
- Restrict Hermes with an explicit tool allowlist.
- Leave `--dangerously-enable-trading` absent unless live trading is intentionally required.
- Start with low KRW and USD order limits.
- Keep the approval URL on loopback or HTTPS.
- Run one server worker and one instance unless preview state is moved to a safe shared store.
- Restrict external access to `/healthz`, `/readyz`, and `/approvals/*`.
- Preserve the non-root, read-only filesystem, dropped capabilities, and no-new-privileges Compose
  controls.

## Order safety invariants

- Trading tools are not registered without the explicit dangerous process argument.
- A write requires an unexpired, externally approved, single-use preview.
- Price, exchange rate, availability, order state, and configured limits are revalidated before
  dispatch.
- Writes are never automatically retried, including after token expiry, rate limits, timeout,
  network failure, or upstream 5xx responses.
- `order-state-unknown` requires order-history inspection before any further write.
- Orders must not be split to evade configured or hard limits.

## Incident response

If credential exposure or unexpected order activity is suspected:

1. Stop the MCP server.
2. Revoke or rotate the Toss API client credentials and MCP token.
3. Replace the human approval token and update only its stored SHA-256 digest.
4. Inspect Toss order history directly through a trusted interface.
5. Preserve sanitized logs and request IDs.
6. Review host, Docker, reverse-proxy, Hermes, and secret-manager access.
