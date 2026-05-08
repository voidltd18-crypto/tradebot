TradeBot IBKR Migration v1.4

Replace:
backend/main.py

Add to requirements.txt:
ib_insync==0.9.86
nest_asyncio==1.6.0

Render Environment Variables:

BROKER=ibkr
IBKR_HOST=127.0.0.1
IBKR_PORT=7497
IBKR_CLIENT_ID=1
IBKR_ACCOUNT=YOUR_ACCOUNT_ID

TWS / Gateway:
Paper:
7497

Live:
7496

Test after deploy:
GET /broker-status

Expected:
{
  "broker": "ibkr",
  "ibkrConnected": true
}

This package ADDS IBKR support while keeping Alpaca fallback.
