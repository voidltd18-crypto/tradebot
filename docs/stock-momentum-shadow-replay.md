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


## Export FMC bars directly from Alpaca, without any order calls

The branch contains `scripts/export_fmc_alpaca_bars.py`. It uses the
official [Alpaca historical single-stock bars endpoint](https://docs.alpaca.markets/us/v1.4.2/reference/stockbarsingle-1),
only issuing GET requests to `data.alpaca.markets`. It does **not**
call trading endpoints, read positions, or submit orders.

Set `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` securely in your local
terminal environment (never paste them into the chat or commit them).
On Windows PowerShell, after setting these variables in your current
session, run from the repository root:

```powershell
python -m scripts.export_fmc_alpaca_bars --start 2026-11-09T14:30:00Z --end 2026-11-09T21:00:00Z --feed iex --out fmc_2026-11-09_1min.csv
python -m scripts.replay_fmc_csv fmc_2026-11-09_1min.csv --symbol FMC --source "Alpaca IEX raw 1Min 2026-11-09" --entry-price 5.485
```

The first command fetches bars into a file **only on the computer where it
is executed**. The second runs the hypothetical strategy comparison;
neither performs paper/live trades. The export defaults to IEX, which may
represent a small subset of trading activity; SIP requires sufficient
market-data entitlements. A single day of IEX bar closes does not
establish intrabar spike execution quality or reliable trailing exits.

Prices from November 9 are **not** a full replay of a position purchased
during or after November 9; align the replay interval with verified
purchase timestamps. Run multiple distinct historical sessions and
estimate half-spread, delay and slippage under stress. Never claim
positive expectancy from a single anecdotal rebound.

The current branch contains exporter code and mocked tests, but it does
**not** contain fetched, independently verified FMC historical bars.
Likewise, there has been **no verified Alpaca paper execution**.


## Offline paper-order lifecycle rehearsal

The module `backend/stock_exit_paper_rehearsal.py` is an **offline**
broker-order-state validator. It cannot initiate a paper or live sell and
does not import an Alpaca trading client. Its tests verify:

- fresh quote/market-open/account-permission prerequisites;
- no fresh hypothetical exit while a sell order is pending or
  partially filled;
- fail-closed behaviour for unknown order status or future/stale quotes;
- cumulative fill reconciliation, terminal rejections, and consistency
  of order IDs and requested quantity.

The `wouldPassPreflight` diagnostic is **not** permission to execute.
It does not independently verify fresh position quantities, available
shares, strategy constraints, PDT, broker restrictions, database
idempotency or actual account state. Successful unit tests are not proof
that any real Alpaca paper order will be filled or safely retried.

### Remaining gates before real paper-trading experiments

1. Import and verify authentic FMC intraday data (currently missing).
2. Review the current stock sell path and all competing exits
   against a fixed, committed test snapshot.
3. Persist order IDs and position peak state across restarts.
4. Add a **paper-only** broker adapter with a hard configuration guard
   proving Alpaca's paper endpoint; test rejected and partial fills
   against the actual paper account, with explicit authorization.
5. Keep production order execution unchanged unless separately
   approved after observing results.

## Restart-safe position state and PAPER account read-only inspection

- `backend/stock_exit_state_store.py` stores a per-position observed peak
  and atomic one-shot hypothetical exit reservation in a SQLite file.
  Reservation blocks a second attempt after process restart. It requires a
  stable position key from verified entry identity. Once reserved it remains
  blocked until explicit independently broker-verified flat reconciliation.
- The file **must** be on persistent storage or it will not survive an
  ephemeral-host filesystem replacement (Render deployments may replace
  ephemeral disks). A production-quality store should use a durable shared
  database with a uniquely indexed idempotency key before any execution
  integration. This offline module is not wired to the live stock engine.
- `backend/stock_paper_account_reader.py` is a GET-only client that
  hard-restricts its base URL to Alpaca's paper hostname, and can read the
  paper account, FMC position, and orders for manual verification. It has
  **no buy, sell, cancel, or submit methods**. Do not pass live credentials.
- CI uses injected HTTP responses and temporary SQLite files. Passing tests
  do not establish that the connected Alpaca paper account was contacted.

**Outstanding:** Obtain genuine FMC market-data exports; authenticate with
a PAPER account in a controlled environment, reconcile actual paper account
position/order statuses; demonstrate durable state on deployment storage;
and review existing live sell precedence and regulatory safeguards. PR stays
draft and no live or paper orders have been placed.


## Final single-command read-only audit (does not deploy)

The complete evidence checklist and hypothetical costed comparison are now
available from one command after obtaining an FMC CSV:

```bash
python -m scripts.audit_fmc_spike_release fmc_2026-11-09_1min.csv --source "Alpaca IEX 1Min FMC, 2026-11-09" --entry-price 5.485 --spread-bps 20 --slippage-bps 15
```

For optional **read-only** PAPER account confirmation, set only
`ALPACA_PAPER_API_KEY_ID` and `ALPACA_PAPER_API_SECRET_KEY` in
your local session, then append `--paper-read-only`. The paper host is
hard-restricted; this command cannot place orders. Do not use live credentials.

The report always keeps `releaseReady: false` until independent historical
provenance, out-of-sample economic evidence, real paper fills and operational
gate/persistence validation have been established elsewhere. The fact that a
paper account exists is NOT a paper order execution test. As of the PR's
construction, no real FMC data has been retrieved by this code and no paper
order has been placed. A paper sell test must use a separately designed
paper-only execution harness and explicit approval; this branch only reads
account data and simulates outcomes.

### Deployment decision
**No-go for live activation.** Keep the PR draft; all new functionality is
either an authenticated read-only diagnostic route or unconnected offline
script/module. Production trading rules remain unmodified. Use the existing
Alpaca/FMC holding protection rather than assuming any simulated trailing
stop has reached the live engine.
