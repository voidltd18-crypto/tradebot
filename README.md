# Profit Optimiser + Analytics + Auto-Improve Package

Includes:
- Profit optimiser with daily target/loss guardrails
- Analytics dashboard with profit factor and average win/loss
- Best and worst stocks
- Auto-blacklist, auto-reduce, and auto-boost based on matched closed trades
- Builds on your working SQLite + full Alpaca backfill system

Render:
Build: pip install -r backend/requirements.txt
Start: uvicorn backend.main:app --host 0.0.0.0 --port $PORT

Keep persistent DB:
SQLITE_DB_FILE=/var/data/trades.db
