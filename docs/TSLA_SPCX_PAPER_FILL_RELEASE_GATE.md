# V19 TSLA/SPCX safety release gate (6 November 2026)

## Current production state
- Render deployment at commit `5b1076b32b4c72fcc2161b1a82af756c6a5a7cef` was live at 05:15 UTC on 5 November.
- `TRADEBOT_STOCK_BUYS_PAUSED` defaults to true. DO NOT remove the pause as part of this test.
- Live broker startup preflight logged valid issuer identities for TSLA and SPCX.
- Production scan on 6 November showed both symbols rejected at account gates; there was no qualified stock portfolio.
- Existing `tests/test_two_stock_paper_order_cycle.py` tests an **in-memory** fake broker. This is not proof of an Alpaca paper fill.

## Verified overnight gap risk
In `backend/legacy/monolith.py`, the main bot loop returns early when
`get_effective_market_status_payload()["isOpen"]` is false. It does NOT
call `manage_money_mode_positions()` while the market is closed. Existing
stop-loss, emergency-stop, and trailing-stop conditions in that function
submit market orders only when the function runs; they are NOT broker-held
stop orders and cannot guarantee the exit price after an overnight gap.

In addition, that manager runs only when `bot_enabled and not emergency_stop`.
Do not infer that a profitable closing mark guarantees an overnight floor.
Review positions and stop execution risk before any live buy reactivation.

## Real paper-fill gate (NOT YET PASSED)
Run from repo root, with **separate Alpaca PAPER credentials only**. Never
copy production keys into the paper variables. Use an empty paper account
with no positions or outstanding orders, sufficient paper buying power,
and an open regular stock market.

```bash
python -m scripts.verify_two_stock_paper_fill
# After configuring ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET:
python -m scripts.verify_two_stock_paper_fill --symbol TSLA --execute-paper --confirm PAPER-ONLY
```

The script is dry-run without BOTH explicit flags; uses TradingClient with
`paper=True`; checks market clock, asset identity, empty account, and buying
power before submitting a $2 **paper BUY**. It polls the order until the
broker reports **filled** with nonzero filled quantity. A submission receipt
alone does not pass. It does NOT auto-sell; manually close the paper holding.
If it times out or partially fills, inspect the paper account before retrying.
No script run or actual filled order has yet been verified as part of this PR.

### Re-enable checklist
1. Capture genuine paper broker order ID, filled status, filled quantity,
   and average fill price, then manually close test position in paper account.
2. Review real broker positions, orders, risk limits and overnight exposure.
3. Decide an overnight holding policy (explicit exposure cap; avoid assuming
   software-managed stops execute outside market hours).
4. Verify account restrictions/PDT, market clock fallback, and source-data
   degradation under real conditions.
5. Confirm original stock buy pause remains until an **explicit, separate**
   live activation decision. Do NOT deploy a change that unpauses buys.

## Other production observations
- Yahoo `day_gainers` scanner source returned repeated HTTP 429 (rate limits).
- Alpaca market-clock disconnect used NYSE schedule fallback on 6 November.
- These need monitoring independently of the paper-fill gate.

This file and script are diagnostics only; no trading behaviour changes.
