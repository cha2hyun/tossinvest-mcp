---
name: tossinvest
description: Safely inspect Toss Securities market/account data and use guarded trading tools through the TossInvest MCP server.
version: 0.1.0
author: cha2hyun
license: MIT
platforms:
  - linux
  - macos
  - windows
metadata:
  hermes: true
tags:
  - finance
  - stocks
  - toss-securities
  - mcp
---

# TossInvest

Use the TossInvest MCP server for official Korean and US stock market data, account inspection,
and explicitly enabled trading.

Hermes registers the tools with an `mcp_tossinvest_` prefix. Tool names below omit that prefix for
readability.

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
