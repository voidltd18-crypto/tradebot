UI + reports + weekly refresh package

Replace:
backend/main.py
frontend/package.json
frontend/index.html
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/styles.css

Then push to GitHub.

Render:
- redeploy backend

Vercel:
- redeploy frontend
- make sure VITE_API_BASE=https://tradebot-0myo.onrender.com

What changed:
- Weekly Stock Refresh button added to Overview
- Reports page now has price/equity history chart
- Reports page has closed trade history table
- Backend adds /reports if missing
