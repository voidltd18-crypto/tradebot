# TradeBot V13 — Autonomous Long-Term AI Memory

Deploy by replacing the existing `backend` folder. Render command remains:

`uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

New automatic, advisory-only endpoints:

- `GET /v13/memory/status`
- `GET /v13/memory/knowledge`
- `GET /v13/memory/events`
- `GET /v13/memory/constitution`

The memory worker runs automatically every 30 minutes by default. It consolidates persisted evidence from Symbol Reputation, Rule Intelligence, Market DNA, the CEO and Board into confidence-scored knowledge. Repeated evidence strengthens a claim; contradictory or deteriorating evidence lowers confidence; unconfirmed knowledge becomes stale after 45 days.

It cannot place, cancel or alter orders and cannot bypass any existing constitution or operator safeguard.
