# Weekly Auto Universe + Collapsible Controls Package

Adds:
- Weekly Auto Universe Rotation
- Top 12 weekly active stocks
- Keeps proven winners
- Removes weak performers
- Stores chosen universe in SQLite
- Dashboard panel showing selected tickers and reasons
- Collapsible dashboard controls:
  - Main Controls
  - Safety Controls
  - Data & Maintenance Tools

Deploy:
Render build: pip install -r backend/requirements.txt
Render start: uvicorn backend.main:app --host 0.0.0.0 --port $PORT

Keep persistent DB:
SQLITE_DB_FILE=/var/data/trades.db
