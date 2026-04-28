Vercel Market Status Proxy Fix

What this fixes:
- https://tradebot-sand.vercel.app/market-status was returning 404 NOT_FOUND.
- This package adds a Vercel API route at /api/market-status.
- It also adds a Vercel rewrite so /market-status works without changing your frontend code.

Files included:
- api/market-status.js
- vercel.json

Backend target:
- Default: https://tradebot-0myo.onrender.com

Optional Vercel environment variable:
- BACKEND_URL=https://tradebot-0myo.onrender.com

Phone deploy steps:
1. Unzip this package.
2. Upload/merge these files into the root of your Vercel project.
3. Redeploy on Vercel.
4. Test: https://tradebot-sand.vercel.app/market-status

Expected result:
- You should see JSON from your Render backend instead of 404 NOT_FOUND.
