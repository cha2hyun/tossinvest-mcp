---
name: tossinvest
description: Use when reading official Toss Securities market, stock, calendar, exchange-rate, commission, holding, buying-power, sellable-quantity, or order-status data through the TossInvest MCP server. Use tossinvest-trading instead when the user explicitly requests an order create, modification, or cancellation.
license: MIT
metadata:
  hermes:
    category: finance
    tags:
      - Finance
      - Stocks
      - Toss-Securities
      - MCP
    related_skills:
      - tossinvest-trading
    requires_tools:
      - mcp_tossinvest_get_prices
---

# TossInvest Read Workflows

Use the TossInvest MCP server as the authoritative source for the configured Toss Securities
account and supported Korean or US market data. Hermes may prefix tool names with
`mcp_tossinvest_`; names below omit that prefix.

## Safety

1. Treat prices, balances, market sessions, and order states as time-sensitive.
2. State the response retrieval time when it affects the answer.
3. Never request or reveal the Toss client secret, OAuth token, MCP token, approval credential,
   account sequence, or raw account number.
4. Never infer a trade from analysis, comparison, alerts, or portfolio discussion.
5. Do not claim that market data is guaranteed, settled, profitable, or investment advice.
6. Keep KRW and USD separate unless the user asks for conversion; then call `get_exchange_rate`
   and state the rate used.

## Select tools economically

- For a simple current-price request, call `get_prices` directly.
- Call `get_stock_info` when symbol identity, market, security type, or currency is ambiguous.
- Add `get_orderbook`, `get_recent_trades`, or `get_candles` only when the requested analysis needs
  them.
- Call `get_stock_warnings` before discussing trading restrictions or a possible purchase.
- Call `get_market_calendar` before reasoning about whether a market session is open.
- Use `get_holdings`, `get_buying_power`, or `get_sellable_quantity` for account availability.
- Use `list_orders`, then `get_order` when an exact order state or execution detail is needed.
- Use `get_commissions` instead of estimating fees from memory.

## Report results

- Preserve the response currency, timestamp, and request ID when relevant.
- Explain that `list_accounts` intentionally returns redacted metadata.
- Distinguish order group filters (`OPEN` or `CLOSED`) from each order's detailed status.
- If `CLOSED` history is unavailable upstream, report that limitation instead of inventing results.
- If the user explicitly requests an order action, switch to `tossinvest-trading`; do not improvise
  a trading workflow here.
