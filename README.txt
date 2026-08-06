TradeBot V16.7.1 Autonomous Reliability Fix

Fixes:
1. V10 autonomous operator crash: defines profit factor and total realised P&L before proposal logic.
2. V14 Scientist SQLite lock: closes the experiment write transaction before writing its event.

Includes all V16.7 adaptive exit and rotation features.
Replace backend/legacy/monolith.py and redeploy Render.
