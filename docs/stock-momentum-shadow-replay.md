# Stock momentum shadow replay (experimental)

This branch adds a **read-only, authenticated** API preview, not an automatic
background worker. It does not connect to a live Alpaca data stream or place
orders. All observations must be supplied by an authorised caller. No feature
flag is enabled on the production trading engine.

POST `/v19/stock-momentum-replay` with the usual TradeBot API credentials:

```json
{
  "entryPrice": 100,
  "observations": [
    {"timestamp": "2026-11-10T14:30:00Z", "price": 100},
    {"timestamp": "2026-11-10T14:30:10Z", "price": 100.3},
    {"timestamp": "2026-11-10T14:30:20Z", "price": 101},
    {"timestamp": "2026-11-10T14:30:30Z", "price": 102},
    {"timestamp": "2026-11-10T14:30:40Z", "price": 103},
    {"timestamp": "2026-11-10T14:30:50Z", "price": 102.4},
    {"timestamp": "2026-11-10T14:31:00Z", "price": 102.2}
  ]
}
```

Output includes first hypothetical sample-price exits using 0.5% spike / 0.7%
trend trailing giveback, compared against a fixed 0.7% reference baseline.
Activation needs a 2% peak gain and adequate recent data. Spike momentum needs
a 1.5% rise over five consecutive observations. A gap over 120 seconds
clears momentum state, without losing the historical high watermark.

**Limitations:** Results assume instantaneous execution at the observed sample
price, before spread, slippage, fees and tax. No PDT / broker / order-state
simulation, no historical FMC replay, no live market ingestion, no persistence
across processes or sessions. These results are NOT proof of positive returns.
A permanent live rollout requires data timestamps and sampling validation,
position-specific state persistence, reconciliation of existing sell rules,
market-hours tests, paper-trading evidence, and explicit review.

Related: draft PR #186; this remains separate from the original selling rules.


## Execution cost simulation (separate preview)

POST `/v19/stock-momentum-cost-preview` using the same payload as the
replay endpoint. Optional `costAssumptions` supports
`spread_bps`, `exit_slippage_bps`, `entry_slippage_bps`,
`fee_per_side_usd`, `shares`, and `max_fill_delay_seconds`.
Defaults are 20 bps spread, 15 bps exit slippage, 1 share, and
no commissions. These are examples, not measured FMC fills.

The model waits for the next chronological sample after a signal,
refuses fills if that quote is more than 120 seconds later, and reports
`NO_SIGNAL`, `NO_NEXT_QUOTE`, `STALE_NEXT_QUOTE`, or
`SIMULATED_FILL`. It compares the same observations with a hypothetical
0.7% trailing reference. Neither model is the entire live TradeBot
strategy, which includes other exits and regulatory/account gates.

## Replay FMC from a real, verified provider CSV

Obtain **chronological intraday historical bar data for FMC** from an
authorised market data source, e.g. an Alpaca historical export made
with your own entitled API credentials. Do not commit keys or private
account data. Prepare a CSV with `timestamp` (offset-aware ISO
8601) and `close` (USD bar close); max 5,000 rows per run.

```bash
python -m scripts.replay_fmc_csv fmc_1min.csv \
  --symbol FMC --source "Alpaca 1-minute export, YYYY-MM-DD, feed and adjustment noted" \
  --entry-price 5.485
```

The CSV runner will *always* identify the source as operator-supplied and
unverified. Minute close prices omit intrabar extremes and bid/ask spreads;
use multiple trading days and varied cost assumptions. **This repository
does not currently contain an independently verified FMC historical CSV.**
Without it, there are no genuine FMC results to report.

## Paper-verification gate (not yet executed)

1. Confirm actual live exit precedence, duplicate-order prevention,
   market-hours/PDT rules, and no accidental sell after a stale or
   missing quote.
2. Reconcile quotes against Alpaca timestamps and persist per-position
   peaks across worker restarts and overnight gaps.
3. Dry-run with broker **paper** credentials only; verify order status,
   partial fills, and broker rejection responses.
4. Compare realised paper execution to simulated spreads, slippage,
   and observed signals over multiple independently verified episodes.
5. Keep live opt-in OFF until the evidence is reviewed. There has
   been **no broker paper order or live order** as part of this PR.
