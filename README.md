# Final Mobile Trading Bot Package

This is the full drop-in package for GitHub upload.

Includes:
- Working Alpaca full order backfill
- SQLite trade memory
- Matched BUY → SELL closed trades
- GBP conversion
- Profit optimiser
- Analytics dashboard
- Auto-improve logic
- Weekly Auto Universe Rotation
- Visible Weekly Auto Universe panel
- Collapsible mobile-friendly control sections
- Timeline fallback to closed trades

Deploy:
Render build: pip install -r backend/requirements.txt
Render start: uvicorn backend.main:app --host 0.0.0.0 --port $PORT

Recommended env:
SQLITE_DB_FILE=/var/data/trades.db
DASHBOARD_API_KEY=your-password
