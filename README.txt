Quality Build Weekly Final Fix

Replace:
backend/main.py

Fix:
- build_weekly_universe() no longer uses stock-memory scoring.
- Weekly refresh now forces quality-only list:
  NVDA, AMD, MSFT, AAPL, META, AMZN, GOOGL, GOOG, AVGO, NFLX, TSLA, PLTR, UBER, QQQ, SMH

After deploy:
1. Open /weekly-universe
2. Click Weekly Stock Refresh
3. Check /status autoUniverse only shows quality names.
