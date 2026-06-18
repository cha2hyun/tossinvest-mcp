# TossInvest MCP

[한국어](README.md)

A safe, Docker-ready Model Context Protocol server for the official
[Toss Securities Open API](https://developers.tossinvest.com/docs).

It exposes Korean and US stock market data, account data, holdings, order history, and optional
guarded trading tools to MCP clients such as Hermes Agent.

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
- Conservative KR market-order checks using the official upper price limit
- Streamable HTTP MCP transport with Bearer authentication and Origin validation
- Hardened Docker Compose deployment
- Hermes Agent configuration and a safety-focused Hermes skill

## Quick start

```bash
git clone https://github.com/cha2hyun/tossinvest-mcp.git
cd tossinvest-mcp
cp .env.example .env
openssl rand -hex 32
```

Put the generated token and your Toss credentials in `.env`, then start the server:

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/healthz
```

The MCP endpoint is `http://127.0.0.1:8000/mcp`.

See the [Korean README](README.md) for the complete setup, Hermes integration, trading safeguards,
operations, and troubleshooting guide.

## License

[MIT](LICENSE) — Copyright (c) 2026 cha2hyun
