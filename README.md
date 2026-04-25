# Faster Exit + Full ALL Orders Backfill Package

This fixes the backfill filter by requesting ALL Alpaca orders instead of only CLOSED orders.

## Why this matters
Some Alpaca setups return zero orders when using CLOSED filtering.
This version uses ALL orders, then filters locally for filled orders.

## Includes
- Faster Exit / Partial Profit Mode
- SQLite persistent trade memory
- Full paginated backfill in 500-order chunks
- ALL order status backfill
- FIFO BUY → SELL closed-trade matching
- GBP conversion
- Debug endpoint: /debug-orders

## After deploy
1. Open dashboard
2. Click `Full Backfill ALL Alpaca Orders`
3. Click `Rebuild PnL Matching`
4. Click Refresh

## Debug
Open:
https://YOUR_RENDER_URL/debug-orders

If count is 0, Alpaca is returning no orders for those API keys.
If count > 0, backfill should import them.

## Render settings
Build:
pip install -r backend/requirements.txt

Start:
uvicorn backend.main:app --host 0.0.0.0 --port $PORT

## Persistent DB recommended
Set env:
SQLITE_DB_FILE=/var/data/trades.db

Attach Render persistent disk at:
/var/data
