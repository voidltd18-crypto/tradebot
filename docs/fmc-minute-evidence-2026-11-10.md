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
