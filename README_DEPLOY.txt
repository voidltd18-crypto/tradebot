Replace these files in your repo:

backend/main.py
frontend/package.json
frontend/index.html
frontend/src/main.tsx
frontend/src/App.tsx
frontend/src/styles.css

Then redeploy Render and Vercel.

Test backend after Render deploy:
/version
/status
/reports
/search-stocks?q=AMD

Vercel env must have:
VITE_API_BASE=https://tradebot-0myo.onrender.com
