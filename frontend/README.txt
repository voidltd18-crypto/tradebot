TradeBot V15.13 Frontend — Decoupled Reports Loading

Replace your frontend src/App.tsx with the included file and deploy to Vercel.

Changes:
- /status is the sole source of connection state.
- /banking-status loads alongside status but cannot hold the page offline.
- /reports loads independently in the background.
- Reports has a 30-second timeout, independent error message and retry button.
- Positions and manual sell controls remain available if reports is slow or unavailable.
- Reports are no longer requested every 10-second live polling cycle.
