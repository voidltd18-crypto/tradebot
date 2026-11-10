# Pre-market legacy stock-selling audit — 10 November 2026

**Source audited:** `backend/legacy/monolith.py` in the GitHub PR
merge checkout. This is *source* verification, **not a Render runtime
or Alpaca brokerage validation**.

Audit runs:
- [Legacy source inspection](https://github.com/voidltd18-crypto/tradebot/actions/runs/42822928537)
- [Full trailing-branch inspection](https://github.com/voidltd18-crypto/tradebot/actions/runs/42822826369)
- [Runner source inspection](https://github.com/voidltd18-crypto/tradebot/actions/runs/42823048767)

## Verified code structure

- `manage_money_mode_positions` (source lines 4877–5057) starts with an
  `has_open_order(symbol)` gate; it invokes fast stop, emergency stop,
  adaptive stop, peak exhaustion, one-hour profit exit, partial profit,
  stall exit and finally money-mode trailing profit.
- Trailing activation at lines 5010–5022 uses **remembered position
  high-water mark**. A current quote falling back beneath the activation
  price logs `ARMED_PULLED_BACK`, but does not itself disable trailing.
- An armed trailing breach at lines 5029–5051 can be delayed by the
  `_v17_runner_trail_decision` check, which permits a confirmation check
  for shallow reversals. Confirmed positive-profit trailing exits are
  not blocked by HOLD AI, but still pass the `pdt_aware_should_avoid_sell`
  gate. Thus a triggered signal is **not guaranteed** to execute.
- `_v17_runner_trail_decision` (lines 4651–4722) counts consecutive
  qualifying shallow floor breaches; recovery resets the count, and
  deep/weakening breaches bypass grace. New isolated runtime regression
  tests compile only this AST function, without importing the live engine.
- `market_sell_qty` (lines 2212–2297) submits a broker sell order,
  records the returned ID/status where available, registers a pending
  sell and logs if this registration fails. Source does not prove
  accepted orders were ever filled.
- Risk percentages in this function are taken from the current
  `risk_profile` if present, otherwise legacy global fallbacks.
  Consequently values from `backend/config.py` alone are **not
  authoritative production settings**.

## Important unverified points

1. Effective Render environment variables, risk profile, worker
   execution flow, and active deployed SHA have **not** been verified.
2. The actual paper account and FMC historical feed were not checked:
   the read-only GitHub workflow failed at the missing PAPER secret gate.
3. Pending-order persistence and rejections need order-level evidence.
4. Original FMC trade entry time and fill price remain unverified;
   historical simulations cannot be attributed to that live position.
5. The experimental 0.5% spike giveback did **not** demonstrate a
   profit advantage in the five-session research study.

## Decision

**NO-GO on merging PR #186 or enabling new live Spike Mode rules.**
Retain existing production protections. This audit adds only read-only
source inspections and isolated tests; it changes no stock trading
logic or broker positions.


## Subsequent sell-submission lifecycle inspection (source and mock tests)

The real `market_sell_qty` function (lines 2212–2297) was inspected
in full. It distinguishes **order submission from execution** and moves
the order into `PENDING_FILL_RECONCILIATION`, which is correct in
principle. Broker-rejected submissions raise and call a rejection
handler, whereas accepted order IDs are registered for reconciliation.

**Confirmed operational risk:** if
`register_pending_sell_order(order_id, ...)` returns `False`, the
function currently **only prints `SELL ACCOUNTING WARNING` and proceeds**.
The accepted broker order cannot be undone by simply raising or retrying,
so any fix must reconcile by broker order ID before permitting new orders
or changing peak state. This is a *reliability gap*, not evidence of a
specific lost FMC fill. The stock caller also clears its remembered high
after a broker submission, before an independently confirmed fill.
These operations should be reviewed together; modifying one in isolation
risks incorrect state transitions or duplicate sells.

Isolated AST regression tests in
`tests/test_legacy_stock_sell_submission_lifecycle.py` characterize
accepted acknowledgements, broker submission errors, failed pending
registration and zero quantity. All network interactions are mocks.

**Release decision remains NO-GO** until broker-reconciliation
failure handling and durable state have verified recovery tests.
No production monolith edit or real order executed.


## 10 November: isolated durable sell journal prototype

Implemented `backend/stock_sell_recovery_journal.py` and
`tests/test_stock_sell_recovery_journal.py` on the draft PR branch.

- Transactional reservation before any attempted sell; only one concurrent
  attempt wins the claim for a given symbol and stable position identity.
- Unknown submit acknowledgment or pending-order persistence errors remain
  blocked from duplicate resubmission, including after a local process restart.
- Accepted broker order ID, partial fills, cancels and terminal statuses
  are recorded against the reservation; the same lot is **never silently
  retried**. Broker order ID and cumulative fills cannot regress.
- A final filled order requires an independently fresh flat position to
  obtain `VERIFIED_FLAT` journal status. The prototype does not itself
  submit orders or compute realised P&L.

**Crucial deployment limitation:** the reference implementation uses
SQLite. It only survives restarts when its file lives on a durable disk
visible to the same worker and does not provide safe cross-host locking.
Do not connect it to multiple ephemeral Render instances. A true
production migration needs the existing persistent database,
verified worker ownership, recovery on startup, and broker-order
reconciliation before any new order is submitted.

These are offline regression checks, **not** a deployed production fix.
The current live `market_sell_qty` and high-water mark reset are
unchanged. No money or orders have been touched.


## Shared PostgreSQL recovery adapter — 10 November 2026

Draft branch now includes:
- `backend/sql/stock_sell_recovery_postgres_v1.sql`: dedicated
  `tradebot_stock_sell_recovery_v1` schema with unique stable attempt
  and broker-order identities
- `backend/stock_sell_recovery_postgres.py`: SQL-atomic reservation,
  acknowledged broker order identity, unknown outcome quarantine,
  cumulative filled-quantity protection, terminal order reconciliation
  and verified-flat record (without permitting same-position re-entry)
- `tests/test_stock_sell_recovery_postgres.py`: offline SQL compatibility
  checks for process reattachment, identity mismatch, canceled/partial
  fills, terminal-to-working rejection and fail-closed DB outage

[Latest passing stock tests](https://github.com/voidltd18-crypto/tradebot/actions/runs/42829257975)

**Explicit scope:** this adapter has not been installed or called by
`backend/legacy/monolith.py`, has not been run against a real PostgreSQL
instance, has no configured Render database, and does not automatically
migrate any existing data. The local test harness uses SQLite for compatible
SQL statement semantics, not real PostgreSQL isolation verification.

### Required steps before any production cutover

1. Provision/identify a **TradeBot-owned**, durable PostgreSQL database
   isolated from the separate Project AI project, with encrypted connection.
2. Apply reviewed migration to a staging branch/database only; verify
   PostgreSQL connection, concurrent insert semantics and transaction
   rollback under injected failures.
3. Implement deterministic broker-side `client_order_id` for every
   attempt. On unknown response, **query the broker by that ID**
   before any retry; never assume a timeout means no order.
4. Integrate under a **disabled-by-default stock-only feature flag**.
   Reserve and persist BEFORE placing a sell, recover broker acknowledgements
   and fills on restart, and block fresh attempts for unknown orders.
5. Keep the existing high-water mark until confirmed flat or verified
   position reduction, rather than resetting it immediately at submission.
6. Check single-worker ownership, old database migration compatibility,
   sell lock/PDT rules, and order fills/cancellations with a dedicated paper
   account before considering a controlled production rollout.

**Decision remains NO-GO for live activation.** Existing production
selling code, settings, broker orders and deployments remain unchanged.


## Pre-market safety coordinator (isolated, no live worker attachment)

Added `backend/stock_sell_coordinator.py`, an injected stock-only
coordinator with deterministic `tb-stock-sell-<digest>`
`client_order_id`. It checks the authoritative position, working orders,
broker client ID and durable reservation **before** asking the injected
broker to submit. On an acknowledgement timeout, uncertain order identity,
or journal acknowledgement persistence failure, the reservation remains
blocked. `recover()` reads the broker's order by client ID and reconciles
authoritative position and cumulative fills; it never submits a new order.

Contract-level regression tests:
`tests/test_stock_sell_coordinator.py`, including timeout *after*
broker acceptance, database acknowledgement outage, duplicate attempt,
broker-read failure, mismatched positions and read-only recovery.

CI:
https://github.com/voidltd18-crypto/tradebot/actions/runs/42829921233

**This is not a deployment.** Production still lacks a validated
broker adapter implementing exhaustive `client_order_id` lookup,
a TradeBot-owned shared Postgres instance with migration, a disabled-by-
default integration in the legacy sell worker, and paper-broker execution
verification. The stock coordinator has no established market-open, PDT,
quote-freshness or full current-rule permission of its own: these must
remain authoritative external gates. Keep the PR draft, unmerged and
live settings untouched.


## Paper-only Alpaca SDK adapter (experimental)

Added `backend/stock_sell_alpaca_paper_adapter.py` plus isolated mock
tests. Its `make_paper_broker()` factory creates an Alpaca
`TradingClient(..., paper=True)` using dedicated paper credentials.
It implements the coordinator contract for fresh stock position
quantity, bounded open orders, lookup by deterministic
`client_order_id`, and paper stock market SELL submission. Missing
position/order is accepted only on an explicit API 404; authentication,
timeout and server failures propagate and block the proposed order.
Broker acknowledgements are validated against symbol, side and client ID.

The adapter is **not connected to `backend/legacy/monolith.py`** and no
paper or real order was submitted during mock tests. Alpaca SDK
signatures were checked against its published API documentation;
integration with a real paper account remains unavailable.

Production NO-GO until actual paper tests, provisioned shared database,
fresh market/PDT/full-strategy gates, deployed SHA verification, and
authoritative post-fill reconciliation are proven. Do not merge or
activate this research branch for the approaching market open.


## Existing Render disk alternative / SQLite storage audit

Read-only Render metadata confirms the stock backend has one instance and
a 100 GB persistent disk at `/var/data`. The checked-in legacy source
sets `SQLITE_DB_FILE` from the environment, falling back to
`persistent_file("trades.db")`; its persistent-file selection uses
`/var/data` when available. `db_connect()` enables SQLite WAL and
a bounded busy timeout. These source facts do **not** prove the live
environment lacks an overriding `SQLITE_DB_FILE` setting.

Added `backend/stock_sell_recovery_disk.py` and
`tests/test_stock_sell_recovery_disk.py` to rehearse recovery
reservations in the **same existing on-disk SQLite database** alongside
legacy tables. The tests check reboot-like reopening, duplicate attempt
blocking, WAL persistence, rejection of non-mounted or missing database
files and symlinks. This is a narrower, practical alternative to adding
a new shared PostgreSQL server for the existing single-instance service.

Render's logs also show `DB WRITER SLOW` warnings, including
`_v13_upsert_knowledge` operations around 30 seconds on 10 November.
Those are performance symptoms; no code-level root cause is yet proven,
and we should NOT disable knowledge persistence or change SQLite
durability pragmas without a measured regression test.

**No live changes.** A durable stock sell recovery cutover still
requires broker-idempotent client order IDs wired to the real submission
path, effective runtime DB path confirmation, startup broker
reconciliation and paper order tests. The disk adapter is isolated.


## 10 November: real journal + coordinator integration and paper startup audit

- Fixed a verified integration defect: `SafeStockSellCoordinator.recover()`
  previously passed `order_id` to the SQLite journal although the
  journal API requires `broker_order_id`. The PostgreSQL prototype
  now uses the same keyword contract.
- Added `tests/test_stock_sell_recovery_end_to_end.py`: actual SQLite
  journal with simulated process restart, accepted broker acknowledgement,
  partial fill, canceled order and acknowledgement timeout. There is
  only one mocked sell submission across the restarted coordinator.
- Closed SQLite connections explicitly after journal operations, guarded
  journal terminal-to-working status regressions, and required matching
  order **symbol**, **side** and deterministic client ID in both
  acknowledgement and recovery.
- A broker timeout now returns `submitted=None` /
  `submissionUncertain=True` rather than falsely asserting no order
  was sent.
- Added `backend/stock_sell_startup_audit.py` to read outstanding
  journal records in SQLite read-only mode, query the independent **paper**
  broker by client order ID and report outcomes without changing
  journal status or issuing a new sell.
- `backend/main.py` has an explicit
  `TRADEBOT_STOCK_SELL_RECOVERY_PAPER_AUDIT_ENABLED=true` gate for
  the startup diagnostic and authenticated
  `/v19/stock-sell-recovery-paper-audit` GET. Without that flag,
  startup performs no audit and the endpoint returns `enabled:false`.
  Even when enabled, it requires `_legacy.PAPER is True`, a verified
  database file under `/var/data`, and dedicated
  `PAPER_ALPACA_API_KEY` / `PAPER_ALPACA_SECRET_KEY`.
- Test coverage includes the opt-in guard and zero broker submission
  from the audit helper.

[Latest passing stock CI](https://github.com/voidltd18-crypto/tradebot/actions/runs/42837306144)

**Scope limitation:** the production `market_sell_qty` function is
still unchanged; its real sell submissions are **not** routed through
the new coordinator. The paper startup audit is not a live startup
broker-reconciliation worker. There are no dedicated paper credentials
available for live paper tests, and effective production database path
is not verified. This remains an unmerged research branch with
production activation **NO-GO**.


## Same-day follow-up: duplicate acknowledgement state regression

Read-only inspection of the actual SQLite journal uncovered another
defect: a second `broker_ack(...)` with the same Alpaca order ID
could reset a previously reconciled `WORKING` or `PARTIAL` record
back to `ACKNOWLEDGED`. The journal now treats matching repeated
acknowledgements as idempotent and retains the reconciled status and
cumulative fill. Tests explicitly verify both working and partially
filled cases across journal reopen.

[Passing stock CI](https://github.com/voidltd18-crypto/tradebot/actions/runs/42838116901)

No changes to production legacy submit path, Render service or
Alpaca account. PR remains draft; paper broker verification and actual
sell-worker integration are still required.
