# Profit Optimised Trading Bot Package

Proper deployable package using your real project structure.

## Structure

backend/
  main.py

frontend/
  src/
    App.tsx
    main.tsx

## Includes

- Profit optimisation
- Weekly Auto Universe panel
- Stock Memory
- SQLite trade storage
- Alpaca full-order backfill
- PnL matching
- GBP conversion
- Mobile-friendly collapsible controls
- Safe one-cycle-per-stock behaviour

## Render settings

Build command:
pip install -r backend/requirements.txt

Start command:
uvicorn backend.main:app --host 0.0.0.0 --port $PORT

## Important env vars

APCA_API_KEY_ID
APCA_API_SECRET_KEY
DASHBOARD_API_KEY
SQLITE_DB_FILE=/var/data/trades.db
