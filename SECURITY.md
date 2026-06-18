# Security Policy

## Reporting

Do not open a public issue for credential exposure, authentication bypass, order-safety bypass, or
another exploitable vulnerability. Report it privately to `cha2hyun.dev@gmail.com` with impact and
reproduction details.

## Deployment requirements

- Keep Toss credentials and `MCP_AUTH_TOKEN` in a secret manager or private `.env`.
- Keep the Docker port bound to localhost unless an authenticated HTTPS reverse proxy protects it.
- Use an unpredictable MCP token and rotate it if it may have leaked.
- Restrict Hermes tools with an allowlist.
- Keep `TOSSINVEST_ENABLE_TRADING=false` unless live trading is intentionally required.
- Start with low KRW/USD order limits and review every preview.
- Never automatically retry a write that returns `order-state-unknown`.
- Treat `/readyz` as operational data and do not expose it unnecessarily.

Only the latest released minor version receives security fixes.
