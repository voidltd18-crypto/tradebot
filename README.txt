TradeBot V16.7 Adaptive AI Exit + Portfolio Rotation

Replace:
  backend/legacy/monolith.py

New behaviour:
- Keep score >= 0.65: HOLD
- 0.55-0.65: rotation WATCH only when a quality-approved replacement is >= 0.15 stronger (3 confirmations)
- 0.45-0.55: EXIT after 2 weak scans
- 0.35-0.45: EXIT after 1 weak scan
- below 0.35: immediate AI thesis exit, subject to same-day/minimum-hold/PDT protections
- replacement must score >= 0.60 and pass the V16 quality guard
- maximum one AI exit per cycle
- normal buy engine runs after an exit and can deploy into the best qualified replacement
- exit evidence is persisted and reviewed at 24h, 72h and 120h

Endpoints:
  GET /v16/exits/status
  GET /v16/exits/reviews

Rollback:
  AI_PORTFOLIO_EXIT_ENABLED=false
  AI_PORTFOLIO_ROTATION_ENABLED=false
