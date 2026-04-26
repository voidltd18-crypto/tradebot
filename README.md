# Weekly Universe Visible Panel Package

This package fixes the missing weekly watchlist display.

Includes:
- Visible Weekly Auto Universe panel
- Top 12 watchlist built directly from Stock Memory / closed trades
- Backend endpoint: GET /weekly-universe
- Refresh Weekly Universe button support
- Keeps current trading features: SQLite, Alpaca backfill, PnL matching, optimiser, analytics, GBP conversion

After deploy:
1. Open dashboard
2. Data & Maintenance Tools
3. Press Full Backfill ALL Alpaca Orders if needed
4. Press Rebuild PnL Matching
5. Press Refresh Weekly Universe
6. The Weekly Auto Universe panel should show the selected stocks

Render:
Build: pip install -r backend/requirements.txt
Start: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
