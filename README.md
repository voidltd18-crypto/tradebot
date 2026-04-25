# SQLite Trade Matching Fixed Package

This package fixes the 0% win-rate / $0 PnL issue by adding proper FIFO BUY → SELL matching.

## What changed
- Adds `closed_trades` SQLite table
- Backfill imports raw Alpaca orders
- Rebuild PnL Matching pairs BUY lots to SELL orders using FIFO
- Calculates realised PnL, GBP PnL, win rate and stock memory from matched closed trades
- Dashboard shows:
  - Raw orders
  - Closed trades
  - Win rate
  - Total realised PnL
  - Matched closed trades list

## How to use after deploy
1. Open dashboard
2. Click `Backfill Alpaca Trades`
3. Click `Rebuild PnL Matching`
4. Click Refresh

## Render Persistent Disk
For permanent DB storage across redeploys, set:

SQLITE_DB_FILE=/var/data/trades.db

and attach a Render persistent disk mounted at `/var/data`.

## Render settings
Build:
pip install -r backend/requirements.txt

Start:
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
