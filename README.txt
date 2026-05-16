Dynamic Market Scanner Upgrade

Replace:
- backend/main.py
- frontend/src/App.tsx

Adds a hybrid dynamic market scanner:
- discovers market movers/active stocks
- filters weak/junk tickers by price, volume and spread
- keeps manual pinned stocks
- keeps core quality universe as a fallback
- exposes dashboard controls and /dynamic-market-scanner endpoints
