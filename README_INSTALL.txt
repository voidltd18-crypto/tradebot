Since Upgrade Tracker update

Replace:
backend/main.py
frontend/src/App.tsx
frontend/src/styles.css

Then redeploy:
- Render backend
- Vercel frontend

Adds:
- Since Upgrade stat on top dashboard
- Since Upgrade tracker in Reports
- Reset Upgrade Baseline button
- GET /since-upgrade
- POST /reset-upgrade-baseline

How to use:
1. Deploy.
2. Open Reports.
3. Press Reset Upgrade Baseline once.
4. From then on, the dashboard shows performance from that point separately from old historical loss.
