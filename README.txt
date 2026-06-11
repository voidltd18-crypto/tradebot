Persistent Memory Safe Patch
============================

This package does NOT remove unrelated features.
It only patches backend persistence so redeploys/restarts can restore:
- Recent trades panel
- locked_today / one-cycle-per-stock-per-day lockouts
- partial profit flags
- temporary loser blacklist
- custom symbols
- trade database location

New backend endpoints:
- GET  /persistence-status
- POST /save-runtime-state

Important Render setup:
For persistence across redeploys, attach a Render Persistent Disk and mount it at:
/var/data

Or set one of these env vars:
- SQLITE_DB_FILE=/var/data/trades.db
- RENDER_DISK_PATH=/var/data

Without a Render disk, the code still saves state, but local app storage may be wiped on redeploy.

Deploy:
Upload/replace backend/main.py. Frontend App.tsx is included unchanged for convenience.
