Frontend Weekly Universe Direct Fix

Replace:
frontend/src/App.tsx

What this fixes:
- Weekly Auto Universe panel now reads directly from /weekly-universe
- It no longer depends only on stale /status.autoUniverse
- Weekly Stock Refresh button immediately refetches /weekly-universe after refresh

Redeploy Vercel after replacing App.tsx.
