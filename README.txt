TradeBot Scanner Quality Safe Patch

Safe patch only. Nothing unrelated removed.

What changed:
- Keeps persistent memory /var/data support intact.
- Dynamic scanner refresh default: 30 minutes.
- Dynamic scanner now rejects flat/negative movers by default.
- Dynamic scanner requires stronger volume, tighter spread, and minimum score.
- Quality universe now focuses on liquid momentum/quality names.
- Slow/weak names that recently caused poor trades are blocked for this strategy: GIS, INTC, KO, RIVN, LCID, SNAP, etc.
- Existing dashboard, banking, reports, manual buttons, persistence, and routes are left in place.

Upload contents to GitHub:
backend/main.py
frontend/src/App.tsx

Render should redeploy automatically.
