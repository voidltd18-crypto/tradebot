Charts update package

Replace:
frontend/src/App.tsx
frontend/src/styles.css

This keeps your repo structure and backend untouched.

Changes:
- Price / Equity History x-axis now uses real time/date labels, not 0/1/2 index numbers.
- Added Daily PnL bar chart on Reports page.
- Kept Weekly Stock Refresh button.

Push to GitHub and redeploy Vercel only.
