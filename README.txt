UI Refresh + Profit Banking Fix

Replace:
backend/main.py
frontend/src/App.tsx

Fixes:
- Button click shows immediate "Request sent" message.
- UI refreshes immediately, again after 1.5s, and again after 4s.
- Restores /banking-status.
- Restores MAX_TRADING_CAPITAL fallback to 260.
- Restores banking payload in /status if supported by your status builder.

Deploy:
1. Render backend
2. Vercel frontend

Test:
https://tradebot-0myo.onrender.com/banking-status

Expected:
enabled: true
maxTradingCapital: 260.0
