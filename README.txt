Restore Search Preview + Pinned Universe

Replace:
backend/main.py

This restores:
- /search-stocks
- /stock-preview/{symbol}
- pinned manual Add to Universe
- /manual-universe

Redeploy Render after replacing backend/main.py.
No Vercel redeploy required unless you change UI files.
