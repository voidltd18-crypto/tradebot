# V15.11 Live Connection and Autonomous Sizing Fix

- `/status` now returns a compact live payload and no longer sends the full historic trade timeline, closed-trade archive, or symbol-memory database every ten seconds.
- Full historic reporting remains available through `/reports`.
- Autonomous position capacity always disables the legacy full-account buy path.
- Capacity-block logs now distinguish structural position limits from insufficient buying power.
- No entry gates, exit rules, stop rules, risk checks, or broker order functions were loosened.
