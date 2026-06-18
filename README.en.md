# TossInvest MCP

[한국어](README.md)

A security-focused Model Context Protocol server for the official
[Toss Securities Open API](https://developers.tossinvest.com/docs).

It exposes Korean and US stock data, market calendars, exchange rates, holdings, buying power,
sellable quantities, commissions, and order history. Live order tools are absent by default.

> This independent open-source project is not an official Toss Securities product and does not
> provide investment advice. Users remain responsible for every submitted order.

## Safety model

- The default command and default Compose file register 16 read-only tools and no trading tools.
- Environment variables cannot enable trading by themselves.
- Trading requires the explicit `--dangerously-enable-trading` process argument.
- Every create, modify, or cancel operation requires an expiring preview and separate human
  approval outside MCP.
- The human approval token is never stored in server or Hermes configuration; the server receives
  only its SHA-256 digest.
- Approved previews are revalidated immediately before dispatch.
- KR market orders use the official upper price limit for safety checks.
- Unbounded US quantity-based market orders and US market modifications are rejected.
- Writes are single-use and are never retried automatically.
- MCP tool annotations and structured output schemas expose the safety profile to agents.

## Read-only quick start

```bash
git clone https://github.com/cha2hyun/tossinvest-mcp.git
cd tossinvest-mcp
cp .env.example .env
openssl rand -hex 32
```

Put the generated value in `MCP_AUTH_TOKEN`. It must differ from
`TOSSINVEST_CLIENT_SECRET`.

Minimal `.env`:

```dotenv
TOSSINVEST_CLIENT_ID=your_client_id
TOSSINVEST_CLIENT_SECRET=your_client_secret
TOSSINVEST_ACCOUNT_SEQ=1
MCP_AUTH_TOKEN=a_separate_random_value
```

Start the read-only server:

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/healthz
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`.

## Hermes

Store only the MCP token in `~/.hermes/.env`:

```dotenv
TOSSINVEST_MCP_AUTH_TOKEN=the_same_value_as_MCP_AUTH_TOKEN
```

Use [`examples/hermes-config.yaml`](examples/hermes-config.yaml) as the read-only allowlist.

Install the read and trading workflow skills:

```bash
mkdir -p ~/.hermes/skills
cp -R skills/tossinvest ~/.hermes/skills/
cp -R skills/tossinvest-trading ~/.hermes/skills/
```

The trading skill declares trading-tool dependencies and stays hidden when those tools are absent.

## Explicitly enabling trading

Generate a separate 32-byte approval token and store the original in a password manager, not in
`.env` and never in Hermes:

```bash
openssl rand -hex 32
```

Calculate its SHA-256 digest without adding the token to shell history:

```bash
read -rsp "Approval token: " APPROVAL_TOKEN
echo
printf '%s' "$APPROVAL_TOKEN" | openssl dgst -sha256 -r | awk '{print $1}'
unset APPROVAL_TOKEN
```

Add only the digest and conservative limits to `.env`:

```dotenv
TOSSINVEST_MAX_ORDER_KRW=1000000
TOSSINVEST_MAX_ORDER_USD=500
TOSSINVEST_APPROVAL_TOKEN_SHA256=the_64_character_sha256_digest
TOSSINVEST_APPROVAL_BASE_URL=http://127.0.0.1:8000
```

Start with the explicit trading override:

```bash
docker compose \
  -f compose.yaml \
  -f compose.trading.yaml \
  up -d --build --force-recreate
```

Trading also requires explicitly adding the six preview and execution tools to the Hermes
allowlist. Never add the approval token or its digest to Hermes.

## Order workflow

1. The agent establishes exact order intent and checks market/account state.
2. A preview tool returns the exact order summary, expiry, and `approval_url`.
3. A human opens the URL and approves with the separate credential.
4. The agent calls the matching execution tool once.
5. The server rechecks price, exchange rate, balance or quantity, order state, and configured limits.
6. The server dispatches once or returns a safe error.

If a write returns `order-state-unknown`, never retry it. Inspect open orders and exact order
details first.

## Development

```bash
uv sync --all-extras
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
uv run pip-audit --strict
uv run python scripts/check_docs.py
uv run python scripts/validate_skills.py
uv run python scripts/update_openapi.py --check
docker build .
```

See the [Korean README](README.md) for the complete tool catalog, deployment guidance, response
format, and troubleshooting reference. Report vulnerabilities according to
[SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE) — Copyright (c) 2026 cha2hyun
