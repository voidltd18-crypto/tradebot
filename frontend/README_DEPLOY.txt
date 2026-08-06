TRADEBOT V16.2 - AI PORTFOLIO VISIBLE FIX

This package is deliberately clean and contains only the active Vite frontend files.
The old duplicate root-level App.tsx has been removed.

DEPLOY:
1. In the frontend project, replace package.json, index.html and the entire src folder with these files.
2. Delete any root-level App.tsx or Appold.tsx files if they exist.
3. Commit and redeploy Vercel without build cache.
4. The navigation must show AI PORTFOLIO between POSITIONS and REPORTS.

The page reads live data from /v16/portfolio/status.
