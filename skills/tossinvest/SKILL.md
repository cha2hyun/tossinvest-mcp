---
name: tossinvest
description: Use when inspecting Toss Securities market or account data, or when safely previewing and confirming stock orders through the TossInvest MCP server.
version: 0.1.0
author: cha2hyun
license: MIT
platforms:
  - linux
  - macos
  - windows
metadata:
  hermes:
    category: finance
    tags:
      - Finance
      - Stocks
      - Toss-Securities
      - MCP
    related_skills: []
    requires_tools:
      - mcp_tossinvest_get_prices
---

# TossInvest Skill

Use the TossInvest MCP server for official Korean and US stock market data, account inspection,
and explicitly enabled trading.

Hermes registers the tools with an `mcp_tossinvest_` prefix. Tool names below omit that prefix for
readability.

## When to Use

- The user asks for Toss Securities market, holding, buying-power, or order data.
- The user explicitly asks to create, modify, or cancel an order through Toss Securities.
- A workflow needs the official Toss market calendar, exchange rate, warnings, or commissions.

Do not use this skill for generic investment advice when no TossInvest MCP data is needed.

## Prerequisites

- The TossInvest MCP server is running and authenticated.
- Hermes has the server configured with the name `tossinvest`.
- Read-only tools are allowlisted; trading tools are allowlisted only when trading is intended.

## How to Run

Load the skill with `/tossinvest`, or ask Hermes to use the TossInvest skill. Verify the integration
before relying on it:

```bash
hermes mcp test tossinvest
hermes skills list | grep tossinvest
```

## Safety rules

1. Treat all market values as time-sensitive and state their retrieval time.
2. Never claim that data or an order is guaranteed, settled, or profitable.
3. Never request or reveal the Toss client secret, access token, MCP token, or account sequence.
4. Prefer read-only tools. Do not infer that the user wants a trade from analysis or discussion.
5. A trade requires an explicit user instruction naming the side, symbol, order type, and amount.
6. Never call an execution tool without showing the complete preview to the user and obtaining an
   explicit confirmation of that exact preview.
7. Pass the exact confirmation phrase returned by the preview. Never invent or alter it.
8. If a tool returns `order-state-unknown`, do not retry. Call `list_orders` and `get_order` first.
9. Do not split an order to evade configured limits or the KRW 100 million hard block.

## Read workflow

For market analysis:

1. Call `get_stock_info` to confirm symbol, market, security type, and currency.
2. Call `get_prices`; add `get_orderbook`, `get_recent_trades`, or `get_candles` only as needed.
3. Call `get_stock_warnings` before discussing a possible purchase.
4. Call `get_market_calendar` before reasoning about whether an order can be accepted now.

For account questions:

1. Use `get_holdings`, `get_buying_power`, or `get_sellable_quantity`.
2. Use `list_orders` and then `get_order` for exact status.
3. Explain currency explicitly and do not sum KRW and USD without an exchange-rate conversion.

## Trading workflow

### Create

1. Confirm stock information, warnings, market calendar, and buying power or sellable quantity.
2. Call `preview_order`.
3. Present symbol, side, type, quantity or amount, price, currency, estimated KRW value, warnings,
   and expiry.
4. Ask the user to confirm that exact preview.
5. Only after confirmation, call `place_order` with the preview ID and exact phrase.
6. Report the returned order detail and status.

### Modify or cancel

1. Call `get_order` first.
2. Call the matching preview tool.
3. Present the current order and proposed change or cancellation.
4. Obtain explicit confirmation.
5. Call the matching execution tool once.
6. Report the newly returned order ID and latest status.

## Pitfalls

- `list_accounts` returns redacted account metadata, not raw account numbers or account sequences.
- KRW and USD balances cannot be added without an explicit exchange-rate conversion.
- A market-order preview is an estimate; the actual execution price can move.
- An expired preview requires a new preview. Never reuse an old confirmation phrase.
- A successful write followed by a failed detail lookup must not be repeated.

## Verification

- `get_prices` returns data and retrieval metadata.
- Trading tools are absent when trading is disabled.
- A write tool rejects a missing, expired, reused, or incorrect confirmation.
- `order-state-unknown` leads to order-history inspection, never an automatic retry.
