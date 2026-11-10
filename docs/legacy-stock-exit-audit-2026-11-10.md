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
