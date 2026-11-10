# FMC minute-bar evidence — 10 November 2026

Research-only evidence from GitHub Actions run:
https://github.com/voidltd18-crypto/tradebot/actions/runs/42814206931

- Dataset: unofficial publicly accessed Yahoo FMC minute-close chart, requested on
  2026-11-10; 5 completed US sessions, 2026-11-03 through 2026-11-09.
- 1,951 one-minute observations across all sessions (390,390,390,390,391).
- Equal hypothetical first-minute close entries for each compared strategy.
- Model: 2% peak-gain activation; 0.5% spike trailing vs hypothetical
  0.7% reference; fill on next observed minute close, with 20 bps
  modeled spread and 15 bps exit slippage, before any tax.
- Results: 0 candidate wins, 0 reference wins, 1 tie (Nov 5),
  4 sessions with no exit trigger for either comparison.
- 2026-11-05 first-minute hypothetical entry $6.43:
  both exit simulations returned +1.3551% after modeled costs.
- 2026-11-09 first-minute hypothetical entry $5.65:
  neither strategy produced a profit-taking exit.
- Separate exploratory replay with $5.485 **assumed** entry on Nov 9:
  both simulations triggered at 14:45 UTC and filled at next sampled
  14:46 close; modeled net return +2.0031% each, zero advantage.
  This does **not** prove the real entry happened before that trigger.

**Interpretation:** In this specific small window, experimental Spike Mode
did NOT demonstrate an advantage over the reference. Not a verified
production-strategy backtest. Since neither model includes all current
TradeBot exit rules, no release readiness conclusions can be extrapolated.
No broker paper/live sell order was submitted.

**Remaining gates:** authenticated Alpaca FMC minute-data replay, verified
position entry timestamps, extended out-of-sample testing and true paper
broker fills, plus persistence and cross-rule integration review. Do not
merge/activate on this evidence alone.


## 12:41 UTC follow-up — include no-signal sessions fairly

Follow-up GitHub Actions evidence:
https://github.com/voidltd18-crypto/tradebot/actions/runs/42817929908

The initial comparison reported only a single comparable session because
4 of 5 days had no profit-exit signal. A new explicit research-only
end-of-session liquidation assumption was therefore added. It computes
hypothetical last-bar exits (with identical estimated trading costs) for
NO_SIGNAL cases, without turning an unfilled/stale sell signal into a fake fill.

Across the same 5 completed FMC sessions:
- All 5 now have model-comparable estimated P&L under that assumption;
- Spike Mode is better in **0**;
- Reference 0.7% hypothetical trail is better in **0**;
- Strategies tie in **5**.

Interpretation: This closes the earlier missing-outcome comparison gap,
but provides **no demonstrated improvement** and is not a validated
actual-broker backtest. Neither strategy simulates the entire production
stock engine, including account locks and other exits. The implied
end-of-day liquidation is an artificial evaluation rule, NOT a TradeBot
live trading setting. Keep release decision **NO-GO**, no merger or
live configuration changes.


## Pre-market review: reference activation discrepancy

The first research baseline required a 2.0% peak gain before the 0.7%
trailing reversal could fire. The repository's `backend/config.py`
instead declares the default `TRAIL_START_PCT=1.2` and
`TRAIL_GIVEBACK_PCT=0.7`. These defaults are **not proof** of the
actual running Render values or the full legacy monolith selling logic.

The replay and cost comparator now offer an explicit optional
`reference_activation_pct=1.2`. Their existing default remains
unchanged to preserve the original research result. Regression tests
confirm a 1.2%-armed reference can trigger where the experimental
2%-armed candidate has no profit-exit signal.

Using the same five public FMC sessions and first-minute hypothetical
entries, the configured-reference *triggered-exit* comparison produced:
one comparable session, zero candidate wins, zero configured-reference
wins and one tie. Four other sessions did not yield two executable
hypothetical profit exits, so that narrow win count is **not a claim of
equivalent profitability**.

Evidence: GitHub Actions
https://github.com/voidltd18-crypto/tradebot/actions/runs/42822344356
and regression tests
https://github.com/voidltd18-crypto/tradebot/actions/runs/42822344364

**Pre-market conclusion: NO-GO for Spike Mode live rollout.**
Do not infer live configuration or full stock engine behavior from the
published strategy defaults. Authenticated paper check previously
failed due missing dedicated PAPER secrets, not market hours. Continue
using existing live strategy without an unverified settings change.
