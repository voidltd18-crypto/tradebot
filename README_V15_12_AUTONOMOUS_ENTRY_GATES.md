# TradeBot V15.12 — Autonomous Evidence-Calibrated Entry Gates

This release lets the AI learn its live Sniper and A+ entry thresholds from completed 24-hour outcomes.

## Behaviour

- Reviews completed, deduplicated outcomes every 30 minutes.
- Excludes blacklisted symbols.
- Requires at least 100 qualifying samples.
- Compares candidate gates across 24h, 72h, 7-day and 30-day windows.
- Requires improved expectancy and profit factor without unacceptable drawdown increase.
- Requires the same eligible candidate for five consecutive reviews.
- Applies only while the market is closed.
- Changes confidence by no more than 0.04 and quality by no more than 0.004 per promotion.
- Learns both A+ and Sniper gates while maintaining a conservative gap between them.
- Records strategy versions so the prior thresholds remain available for rollback.

## Routes

- `GET /adaptive-thresholds/status`
- `POST /adaptive-thresholds/review`

## Optional environment settings

- `AI_THRESHOLD_LEARNING_ENABLED=true`
- `AI_THRESHOLD_CLOSED_MARKET_ONLY=true`
- `AI_THRESHOLD_INTERVAL_SECONDS=1800`
- `AI_THRESHOLD_MIN_SAMPLES=100`
- `V2_OPTIMIZER_REQUIRED_STABLE_RUNS=5`
- `V2_AUTO_APPLY_THRESHOLDS=true`

No order placement, stop-loss, position-capacity or exit logic is changed by this release.
