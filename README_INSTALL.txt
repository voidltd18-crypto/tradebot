Weekly stock refresh update

Backend:
- Replace backend/main.py with backend/main.py from this package.
- This adds:
  POST /refresh-universe
  GET /weekly-refresh-status
  weeklyRefresh in /status where possible
  Monday auto-refresh watchdog

Frontend:
- Open frontend/README_FRONTEND_PATCH.txt and add the small button to your current App.tsx.
- I did not overwrite App.tsx to avoid breaking your just-working UI.

After upload:
- Render redeploys backend.
- Vercel redeploys frontend if you add the UI button.

Button calls:
POST ${VITE_API_BASE}/refresh-universe

Requires your saved dashboard API key in the UI because backend protects trading/admin endpoints.
