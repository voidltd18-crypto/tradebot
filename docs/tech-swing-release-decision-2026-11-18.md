# Tech swing release decision — 18 November 2026

**Decision: NO-GO for live automatic buying.** Keep the existing live trading system unchanged. This branch is research-only; do not merge it as an authorization to trade.

## Verified CI
- Tech swing research safety tests: passed, run 44356045685
- Tech swing forward research snapshot: passed, run 44356045394
- V19 diagnostics: passed, run 44356045460
- V19 opt-in runtime safety: passed, run 44356045557

## Research evidence
Period: 2023-01-03 to 2026-11-17, with approximately 201 aligned trading sessions of indicator warm-up. Not independently out-of-sample.
- One-position tech selector: **+14.05%** account return, **-6.46%** maximum drawdown, 7 closed trades.
- Date-aligned passive tech basket at 25% capital exposure: **+30.59%**, **-10.53%** maximum drawdown.
- Separate 2026 fresh-capital simulation: selector **+3.72%**, passive **+0.37%**; selector drawdown **-5.73%**, passive **-4.26%**.
- Assumptions: synthetic 15bps friction per side; fills and risk estimates are simulations, not live performance.
- First completed snapshot: 2026-11-17, top candidate **AAPL**. This is a point-in-time candidate report, not a live entry or proof of profitable forward trading.
- A second workflow run of the **same dated snapshot** does not count as a second forward session.

## Release gate status
- Passed: positive historical return, full-period drawdown better than -10%, positive 2026 simulation.
- Failed: full-period return did not beat the matched passive benchmark.
- Not verified: 60 actual forward sessions with outcomes; independent broker-side safeguards.
- Gate output: eligibleForLiveReview=false, liveOrdersAuthorized=false, ordersSubmitted=0.

## Engineering next steps (no approval loop)
1. Preserve dated snapshots across future sessions and measure **subsequent realized paper-model outcomes**, with realistic execution assumptions and explicit benchmark comparison. Merely collecting signals must not increment the validation counter.
2. Verify broker-side controls independently before any future live-order proposal: explicit off switch, maximum 25% allocation, one tech position, order deduplication/idempotency, account/buying-power checks, market-hours handling, stale-data rejection, and rollback.
3. Reassess whether simple passive holding is a better weeks-to-months choice. Avoid strategy parameter tuning to make past results look better.
4. Only after stronger evidence, prepare a separate human-reviewed live release proposal. Do not silently switch trading on.

No live orders were submitted by this research.
