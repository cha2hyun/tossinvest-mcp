# TossInvest MCP

[한국어](README.ko.md)

A safe, Docker-ready Model Context Protocol server for the official
[Toss Securities Open API](https://developers.tossinvest.com/docs).

It exposes Korean and US stock market data, account data, holdings, order history, and
optional guarded trading tools to MCP clients such as Hermes Agent.

> This is an independent open-source project and is not an official Toss Securities product.
> It is not investment advice. You are responsible for every order submitted through it.

## Features

- OAuth 2.0 Client Credentials token management with in-memory caching
- All official Open API v1.1.1 read operations
- Per-API-group rate limiting and safe `429` retries for reads
- Account header injection without exposing account identifiers to the model
- Trading tools hidden by default
- Two-step, expiring, one-time confirmations for create, modify, and cancel operations
- Configurable KRW/USD limits and a hard block on orders worth KRW 100 million or more
- Streamable HTTP MCP transport with Bearer authentication and Origin validation
- Hardened Docker Compose deployment
- Hermes Agent configuration and a safety-focused Hermes skill

## Quick start

Prerequisites:

- Toss Securities Open API `client_id` and `client_secret`
- Docker with Compose

```bash
cp .env.example .env
openssl rand -hex 32
```

Put the generated token and your Toss credentials in `.env`, then start the server:

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/healthz
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`.

Copy the relevant section from
[`examples/hermes-config.yaml`](examples/hermes-config.yaml) into
`~/.hermes/config.yaml`, set `TOSSINVEST_MCP_AUTH_TOKEN` in `~/.hermes/.env`, and run:

```bash
hermes mcp test tossinvest
```

## Configuration

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `TOSSINVEST_CLIENT_ID` | yes | — | Toss Open API client ID |
| `TOSSINVEST_CLIENT_SECRET` | yes | — | Toss Open API client secret |
| `TOSSINVEST_ACCOUNT_SEQ` | account tools | — | Fixed account sequence |
| `TOSSINVEST_ENABLE_TRADING` | no | `false` | Register guarded trading tools |
| `TOSSINVEST_MAX_ORDER_KRW` | trading | — | Maximum order amount in KRW |
| `TOSSINVEST_MAX_ORDER_USD` | trading | — | Maximum order amount in USD |
| `TOSSINVEST_BASE_URL` | no | official API | Override only for tests or compatible proxies |
| `MCP_AUTH_TOKEN` | yes | — | Bearer token required by the MCP endpoint |
| `MCP_ALLOWED_ORIGINS` | no | empty | Comma-separated browser origins; absent Origin is allowed |
| `MCP_HOST` | no | `0.0.0.0` | Container listen address |
| `MCP_PORT` | no | `8000` | Container listen port |
| `LOG_LEVEL` | no | `INFO` | Server log level |

Keep `.env` private. Never commit credentials, account identifiers, access tokens, or production
responses.

## Available tools

Read-only tools:

- `get_stock_info`, `get_stock_warnings`
- `get_prices`, `get_orderbook`, `get_recent_trades`, `get_price_limits`, `get_candles`
- `get_exchange_rate`, `get_market_calendar`
- `list_accounts`, `get_holdings`
- `list_orders`, `get_order`
- `get_buying_power`, `get_sellable_quantity`, `get_commissions`

When `TOSSINVEST_ENABLE_TRADING=true`, the server additionally registers:

- `preview_order` → `place_order`
- `preview_order_modification` → `modify_order`
- `preview_order_cancellation` → `cancel_order`

Execution tools require the exact `preview_id` and confirmation phrase returned by the matching
preview. Previews expire after two minutes and can be used once.

If a write request loses its network connection after dispatch, the server returns
`order-state-unknown`. Do not retry it automatically; inspect the order list first.

## Local development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src
```

Run locally:

```bash
uv run tossinvest-mcp
```

Check the official OpenAPI contract:

```bash
uv run python scripts/update_openapi.py --check
```

## Security

The Compose configuration binds only to `127.0.0.1`. If you deploy remotely, put the server behind
an HTTPS reverse proxy, preserve streaming responses, and restrict network access. See
[SECURITY.md](SECURITY.md) before enabling trading.

## License

[MIT](LICENSE) — Copyright (c) 2026 cha2hyun
