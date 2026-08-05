# TradeBot V15 — AI Operations Centre

Automatic monitoring-only control room. Runs every 15 minutes by default and persists full health audits plus alerts.

Endpoints:
- `GET /v15/operations/status`
- `GET /v15/operations/components`
- `GET /v15/operations/alerts`
- `GET /v15/operations/history`
- `GET /v15/operations/constitution`

Environment variables:
- `V15_AIOPS_ENABLED=true`
- `V15_AIOPS_INTERVAL_SECONDS=900`
- `V15_AIOPS_STARTUP_DELAY_SECONDS=75`

No manual review is required. AIOps cannot trade or change settings.
