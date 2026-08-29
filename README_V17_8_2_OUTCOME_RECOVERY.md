# TradeBot V17.8.2 — Outcome Recovery

This patch extends V17.8.1 SIP -> IEX fallback with bounded recovery for historical research outcomes.

## Changes
- Existing stale outcome errors are cleared before each recovery attempt.
- Successful SIP/IEX recovery completes the outcome and clears its error/retry state.
- Genuine historical-data failures get a persistent retry counter.
- Default maximum retries: 3 (`V6_OUTCOME_MAX_RETRIES`).
- After the retry limit, the research row is marked `UNAVAILABLE`, its visible error is cleared, and it is removed from the active ready/error backlog.
- `v2_pending_breakdown()` now reports `unavailable` separately and only counts `PENDING` rows as active backlog.
- V6.6 drain treats quarantined rows as resolved work so it cannot loop on them forever.
- New logs include `V17.8.2 OUTCOME RECOVERY` and `V17.8.2 OUTCOME QUARANTINE`.

## Safety
This is research/outcome-storage logic only. No live entry, exit, position sizing, Profit Vault, Adaptive Universe, trailing, Peak Exhaustion, PDT, or order execution logic was changed.
