TradeBot V16.6 AI Buy and Exit Manager

Replace backend/legacy/monolith.py and redeploy Render.

AI exits:
- Existing hard/emergency stops remain immediate.
- Ordinary AI thesis exits never sell a same-day purchase.
- Default minimum hold: 1440 minutes.
- Weakness must persist for 3 consecutive scans.
- Maximum 1 AI thesis exit per scan cycle.
- Evidence endpoint: GET /v16/exits/status (x-api-key required).

Environment rollback:
AI_PORTFOLIO_EXIT_ENABLED=false
