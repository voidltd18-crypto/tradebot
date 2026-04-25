# GBP Profit Dashboard Fixed Package

This fixes the white-screen crash when:
- market is closed
- scans are empty
- trade timeline is empty
- selected scan is undefined

It also keeps:
- USD/GBP conversion
- GBP values for equity, PnL, positions, trades
- timeline USD/GBP chart toggle
- A+ gate / Sniper / Memory / PDT-aware dashboard sections

## Render settings

Build:
pip install -r backend/requirements.txt

Start:
uvicorn backend.main:app --host 0.0.0.0 --port $PORT

## Vercel
Root directory:
frontend

Build command:
npm run build

Output:
dist
