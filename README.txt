Fixed Login Package

Replace:
backend/main.py
frontend/src/App.tsx

Render backend env vars:
ADMIN_USERNAME=yourusername
ADMIN_PASSWORD=your-strong-password
AUTH_SECRET=another-long-random-secret

Deploy Render and Vercel.

Open:
https://tradebot-sand.vercel.app/?v=login-fixed

The login block is outside useEffect and should show first.
