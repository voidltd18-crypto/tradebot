# TradeBot V18 — Autonomous Weekly Review

V18 adds an advisory-only weekly governance layer on top of V17.9 Decision Audit.

- Reviews the last 7 days of rejected-entry evidence by gate.
- Requires at least 20 completed audited decisions before proposing a gate review.
- Requires at least 8 classified decisions for an individual gate before judging it.
- Marks gates KEEP / OBSERVE / REVIEW using measured good-block vs missed-winner evidence.
- Persists a weekly proposal and requires 5 consecutive stable weekly reviews before it can become BOARD_REVIEW_ONLY eligible.
- It NEVER applies a live strategy change directly.
- Constitutional locks explicitly protect Profit Vault, protected baseline, max-position safety, order execution safety and stop protection.
- New endpoint: GET /v18/weekly-review?days=7
- New dashboard tab: WEEKLY REVIEW

V17.9 remains the evidence collector. Immediately after deployment, V18 will normally show COLLECTING_EVIDENCE until enough post-V17.9 live-market decisions have matured.
