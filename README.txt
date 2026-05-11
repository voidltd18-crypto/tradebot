Force Quality Universe UI Fix

Replace:
backend/main.py

Fixes stale Weekly Auto Universe panel by forcing these endpoints to return the quality-only list:
- GET /weekly-universe
- POST /refresh-universe
- GET /refresh-universe-preview

After Render deploy:
1. Open /weekly-universe
2. Open /refresh-universe-preview
3. Click Weekly Stock Refresh
4. Click Refresh Data / hard refresh browser
