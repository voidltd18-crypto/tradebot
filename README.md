# SQLite Persistent Trade Memory Package

Adds proper persistent trade storage and Alpaca backfill.

## New features
- SQLite database: trades.db
- Every bot BUY/SELL saved to DB
- Timeline loaded from DB
- Stock memory calculated from DB
- Backfill old filled Alpaca orders
- Realised PnL summary in USD and GBP
- Dashboard button: Backfill Alpaca Trades

## Important Render note
For truly permanent storage across redeploys, attach a Render Persistent Disk and set:

SQLITE_DB_FILE=/var/data/trades.db

If you do not set a persistent disk path, SQLite will work but may reset on redeploy/rebuild depending on Render storage behavior.

## Render settings
Build:
pip install -r backend/requirements.txt

Start:
uvicorn backend.main:app --host 0.0.0.0 --port $PORT

## Required env
APCA_API_KEY_ID
APCA_API_SECRET_KEY
DASHBOARD_API_KEY
PAPER=false

## Optional env for persistent disk
SQLITE_DB_FILE=/var/data/trades.db
