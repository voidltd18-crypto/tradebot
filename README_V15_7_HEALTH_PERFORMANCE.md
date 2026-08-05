# TradeBot V15.7 — Non-Intrusive Health Monitoring

This release fixes the remaining false health failures without changing trading logic.

- Recurring Database Doctor is now read-only and bounded.
- Full integrity/write probes are removed from the 15-minute hot path.
- Expensive AI subsystem checks are cached for 120 seconds.
- Database Doctor results are cached for six hours.
- Slow successful checks remain PASS and carry a performance warning instead of becoming failures.
- Reports performance statistics are cached for 45 seconds.
- Operator status is cached for 30 seconds.
- Manual performance rebuild still forces a fresh rebuild.

No order, signal, risk, position or strategy logic was changed.
