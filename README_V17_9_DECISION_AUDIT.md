# V17.9 Decision Audit / Missed Opportunity Tracker

Adds an advisory-only audit trail for live-gate rejections.

- Every persisted REJECTED setup gets 15m, 30m, 1h and 2h forward checkpoints.
- Uses the V17.8.1 historical price path, including SIP -> IEX fallback.
- Classifies evidence as GOOD_BLOCK (<= -0.50%), MISSED_WINNER (>= +1.00%), or NEUTRAL.
- New `/v17/decision-audit?days=7` endpoint.
- New DECISION AUDIT dashboard tab with per-gate effectiveness and recent rejected opportunities.
- Closed-market AI research evaluates matured audit checkpoints.
- Advisory only: no gate, sizing, order, exit, Profit Vault, universe, or risk settings are changed.

Note: V17.9 starts collecting this richer 15m/30m/1h/2h evidence after deployment; it does not invent sub-hour checkpoints for old decisions.
