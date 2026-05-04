Deploy v1.0 production stable

Replace these files if present:
backend/main.py
frontend/src/App.tsx

If you are using the full package, you can also replace:
frontend/package.json
frontend/index.html
frontend/src/main.tsx
frontend/src/styles.css

Then:
1. Push to GitHub
2. Redeploy Render
3. Redeploy Vercel
4. Test:
   https://YOUR_RENDER_URL/version
   https://YOUR_RENDER_URL/search-stocks?q=AMD
