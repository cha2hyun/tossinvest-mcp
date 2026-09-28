# TossInvest MCP

[한국어](README.md)

An independent MCP server for the official
[Toss Securities Open API](https://developers.tossinvest.com/docs).

The server keeps Toss API credentials and account values out of its `.env` and container
environment. MCP clients send them as private request headers, and the server builds an isolated
authentication context per credential fingerprint. Those headers are transport metadata, not MCP
tool arguments or schemas.

## Security properties

- Read-only by default; trading tools require `--dangerously-enable-trading`.
- Public plain HTTP requests are rejected. HTTP is accepted only for loopback-published local
  servers and internal health checks.
- Responses use `Cache-Control: no-store`; HTTPS responses also use HSTS.
- Uvicorn access logging is disabled by default.
- Credential and account fields are redacted from upstream responses and errors.
- OAuth tokens, HTTP clients, rate limits, and previews are isolated per request credential set.
- Writes require an expiring preview, separate human approval, and immediate revalidation.
- Writes are single-use and are never retried automatically.

## Quick start

For production, pin the current stable
[`v0.1.2`](https://github.com/cha2hyun/tossinvest-mcp/releases/tag/v0.1.2) release instead of the
moving `main` branch or `latest` image tag.

```bash
git clone --branch v0.1.2 --depth 1 https://github.com/cha2hyun/tossinvest-mcp.git
cd tossinvest-mcp
cp .env.example .env
docker compose up -d --build
curl http://127.0.0.1:8000/healthz
```

Each GitHub Release includes a Python wheel, source distribution, and SHA-256 checksums. To use the
published multi-architecture GHCR image without rebuilding it locally, pin the complete version:

```bash
TOSSINVEST_IMAGE=ghcr.io/cha2hyun/tossinvest-mcp:0.1.2 docker compose pull
TOSSINVEST_IMAGE=ghcr.io/cha2hyun/tossinvest-mcp:0.1.2 docker compose up -d --no-build
```

The `latest` tag moves with every release. See [RELEASING.md](RELEASING.md) for the release policy.

The server `.env` contains non-secret operational settings only. Store Toss credentials in the MCP
client's secret store. For Hermes, copy [`examples/hermes.env.example`](examples/hermes.env.example)
to `~/.hermes/.env` and use [`examples/hermes-config.yaml`](examples/hermes-config.yaml).

```yaml
mcp_servers:
  tossinvest:
    url: "http://127.0.0.1:8000/mcp"
    headers:
      X-Tossinvest-Client-Id: "${TOSSINVEST_CLIENT_ID}"
      X-Tossinvest-Client-Secret: "${TOSSINVEST_CLIENT_SECRET}"
```

Never copy credential values into prompts, chats, skills, or tool arguments.

If `/mcp` returns `403 {"error":"origin-not-allowed"}`, the client sent an `Origin` header that is
not allowlisted. Add the exact browser or webview origin to `MCP_ALLOWED_ORIGINS`, separated by
commas for multiple origins, then recreate the container. For example:
`MCP_ALLOWED_ORIGINS=http://127.0.0.1:6274,http://localhost:6274`.

After OAuth, the server discovers accounts itself. A single account is selected automatically and
its sequence remains internal. If multiple accounts exist, `list_accounts` returns only a
non-sensitive, 1-based `account_index` and account type. Add the chosen index as the
`X-Tossinvest-Account-Index` connection header; never pass an account sequence as a tool argument.

For VS Code, use [`examples/vscode-mcp.json`](examples/vscode-mcp.json). The trading-mode version is
[`examples/vscode-mcp-trading.json`](examples/vscode-mcp-trading.json). Both use VS Code
`${input:...}` secrets and require only the client ID and secret for account discovery.

```json
{
  "inputs": [
    {
      "type": "promptString",
      "id": "tossinvest-client-id",
      "description": "TossInvest Client ID",
      "password": true
    },
    {
      "type": "promptString",
      "id": "tossinvest-client-secret",
      "description": "TossInvest Client Secret",
      "password": true
    }
  ],
  "servers": {
    "tossinvest": {
      "type": "http",
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "X-Tossinvest-Client-Id": "${input:tossinvest-client-id}",
        "X-Tossinvest-Client-Secret": "${input:tossinvest-client-secret}"
      }
    }
  }
}
```

Do not write actual credentials in JSON. VS Code stores prompted inputs securely and sends them as
connection headers, outside model-generated tool arguments. Remote URLs must use HTTPS.

## Tools

Read-only mode exposes 28 tools covering stock metadata and warnings; prices, order books, trades,
candles, and limits; investor, program, short-selling, credit, and securities-lending activity;
exchange rates, market calendars, rankings, and market indicators; accounts, holdings, buying
power, sellable quantity, and commissions; and regular or conditional order history.

Trading mode adds six preview and execution tools for creating, modifying, and cancelling regular
orders, for 34 tools in total. The official API's conditional-order create, modify, and cancel
operations are intentionally not exposed because they do not yet have the same preview, separate
human approval, and immediate revalidation safeguards.

## Trading

Generate a separate human approval token and store its original outside both the MCP server and
client. Put only its SHA-256 digest and conservative KRW/USD limits in the client secret store.
Then use
[`examples/hermes-trading-config.yaml`](examples/hermes-trading-config.yaml) and start:

```bash
docker compose \
  -f compose.yaml \
  -f compose.trading.yaml \
  up -d --build --force-recreate
```

Every create, modify, or cancel operation follows preview → browser approval → one execution. If a
write returns `order-state-unknown`, do not retry it; inspect order history first.

## Public deployment

Terminate TLS at a trusted reverse proxy and use `https://` for both the MCP endpoint and approval
origin. Preserve the original scheme for Uvicorn and list only the proxy addresses in
`MCP_TRUSTED_PROXY_IPS`. Disable proxy buffering for MCP streaming, and redact
`X-Tossinvest-*`, authorization headers, form bodies, and body dumps from proxy/APM logs. Restrict
health and approval routes and add firewall, VPN, or gateway authentication.

## Verification

The current source uses FastMCP 4.0.10 and MCP Python SDK 2. Tests cover both legacy handshake
connections and the `2026-07-28` sessionless protocol. For the latter, use `/healthz` or list tools
to check connectivity; MCP `ping` is only available on legacy connections.

Active credential contexts are protected from cache eviction. When every context is busy, a new
credential set receives `tenant-capacity-exceeded` and can try again after an active request finishes.
Server errors, transport failures, and missing order IDs after order dispatch return
`order-state-unknown`. Inspect order history before taking further action; do not repeat the write.

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src scripts tests
uv run pip-audit --strict .
uv run python scripts/check_docs.py
uv run python scripts/validate_skills.py
uv run python scripts/update_openapi.py --check
uv build
docker build .
./scripts/run_e2e.sh
```

`run_e2e.sh` starts the production image and verifies MCP HTTP, request-credential isolation,
OAuth, a read call, and error redaction through a local fake upstream. It never uses external APIs
or real credentials.

See [SECURITY.md](SECURITY.md) for supported versions, the threat model, and private reporting
process.
