---
name: tossinvest-trading
description: Use only when the user explicitly requests creating, modifying, or cancelling a Toss Securities stock order through trading-enabled TossInvest MCP tools. Enforce exact order intent, separate human approval, one-time execution, configured limits, and no automatic write retries.
license: MIT
metadata:
  hermes:
    category: finance
    tags:
      - Finance
      - Stocks
      - Trading
      - Toss-Securities
      - MCP
    related_skills:
      - tossinvest
    requires_tools:
      - mcp_tossinvest_preview_order
      - mcp_tossinvest_place_order
---

# TossInvest Trading

Use this workflow only for an explicit user-requested order action. Hermes may prefix tool names
with `mcp_tossinvest_`; names below omit that prefix.

## Non-negotiable rules

1. Never infer an order from research, analysis, portfolio discussion, or a price target.
2. Never request, read, transmit, log, or store the human approval token or its hash.
3. Never split an order to evade configured limits or the KRW 100 million hard block.
4. Never call a write tool before a matching preview has been approved outside MCP.
5. Never call a write tool more than once for the same preview.
6. Never automatically retry any create, modify, or cancel request.
7. If the result is `order-state-unknown`, inspect order history before any further write.
8. Treat a missing trading tool as trading disabled; do not seek another route around it.

## Establish exact intent

For a new order, require:

- side: `BUY` or `SELL`
- symbol
- order type: `LIMIT` or `MARKET`
- exactly one of whole-share `quantity` or supported USD `order_amount`
- `price` for a limit order
- time in force when it differs from `DAY`

For a modification, require the existing order ID and every proposed replacement field.

For a cancellation, require the existing order ID and an explicit request to cancel it. Do not
require creation-only fields such as side or amount.

If any required intent is ambiguous, ask the user before calling a preview tool.

## Create

1. Confirm symbol identity and currency when ambiguous.
2. Check stock warnings and the relevant market calendar.
3. Check buying power for a buy or sellable quantity for a sell.
4. Call `preview_order` exactly once with the user's stated intent.
5. Present symbol, side, order type, quantity or amount, limit price when present, currency,
   estimated value, estimated KRW value, warnings, expiry, and `approval_url`.
6. Explain that market-order execution price may move and that a new preview is required after
   expiry or material changes.
7. Ask the user to open `approval_url` and approve the exact preview with the separate credential.
8. Only after the user reports that external approval is complete, call `place_order` once with the
   preview ID.
9. Report the returned order ID, detailed status, execution data, timestamp, and any warning.

## Modify

1. Call `get_order` and show the current order state.
2. Reject attempts to modify an order that is no longer actionable.
3. Call `preview_order_modification` with the exact requested replacement fields.
4. Present the current order, proposed replacement, estimated value, expiry, and `approval_url`.
5. Wait for the user to report completion of the external approval.
6. Call `modify_order` once with the preview ID and report the replacement order ID and status.

## Cancel

1. Call `get_order` and show the current actionable order.
2. Call `preview_order_cancellation`.
3. Present the exact order being cancelled, expiry, and `approval_url`.
4. Wait for the user to report completion of the external approval.
5. Call `cancel_order` once with the preview ID and report the resulting order ID and status.

## Failure handling

- `approval-required`, `preview-not-found`, or `preview-state-changed`: do not execute. Create a new
  preview only after presenting the changed state and obtaining renewed user intent.
- `order-state-unknown`: do not retry. Call `list_orders(status="OPEN")`; use `get_order` for any
  candidate order ID. If existence remains uncertain, stop all new writes and explain the
  uncertainty.
- A successful write followed by a failed detail lookup is still a successful write attempt. Do not
  repeat it; inspect order history.
- Rate-limit, expired-token, timeout, network, and upstream 5xx errors never justify an automatic
  write retry.
