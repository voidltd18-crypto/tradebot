# GBP Profit Dashboard Package

Adds USD → GBP conversion across the trading dashboard.

## Features
- Live USD/GBP exchange rate from backend
- GBP fallback rate if FX API fails
- Equity shown in USD + GBP
- Buying power shown in USD + GBP
- Cash shown in USD + GBP
- Day PnL shown in USD + GBP
- Position value shown in USD + GBP
- Trade PnL shown in USD + GBP
- Timeline chart can switch between USD and GBP

## Render settings

Build:
pip install -r backend/requirements.txt

Start:
uvicorn backend.main:app --host 0.0.0.0 --port $PORT

## Required Render env vars
APCA_API_KEY_ID
APCA_API_SECRET_KEY
DASHBOARD_API_KEY
PAPER=false
