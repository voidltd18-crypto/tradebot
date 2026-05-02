Stock search / preview package

Replace:
backend/main.py
frontend/src/App.tsx
frontend/src/styles.css

Adds:
- Search tab
- /search-stocks?q=amd
- /stock-preview/{symbol}
- /add-to-universe/{symbol}
- Trading212-style stock preview cards with price, % move, GBP value, mini chart
- Buy and Add to Universe buttons

Then:
- Redeploy Render for backend
- Redeploy Vercel for frontend
