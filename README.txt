Balanced Current View UI Refresh Fix

Replace this file in your repo:
frontend/src/App.tsx

What changed:
- Keeps the current dashboard view/layout.
- Keeps instant refresh after button actions.
- Slows normal background polling to every 10 seconds.
- Adds a guard so polling cannot overlap or spam Render.
- Uses no-store fetches so the UI does not show stale cached data.

After upload, commit to GitHub and let Vercel redeploy.
