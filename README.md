# Faster Exit + Full Order Backfill Package

This adds your paginated old-order backfill idea.

## What changed
- `/backfill-trades` now fetches old Alpaca orders in 500-order chunks
- It pages backwards using `until`, like your sample code
- Stores raw filled BUY/SELL orders into SQLite
- Rebuilds closed trades with FIFO BUY → SELL matching
- Updates realised PnL, GBP PnL, win rate and stock memory

## Buttons
- Full Backfill Alpaca Trades
- Rebuild PnL Matching

## Important
If Closed Trades still shows 0 after this, Alpaca is returning only BUY orders or there are no filled SELL orders in the account history being fetched.

## Render
Build:
pip install -r backend/requirements.txt

Start:
uvicorn backend.main:app --host 0.0.0.0 --port $PORT

## Persistent DB recommended
Set:
SQLITE_DB_FILE=/var/data/trades.db

and attach a Render persistent disk at `/var/data`.
