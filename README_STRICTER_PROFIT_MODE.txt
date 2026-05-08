TradeBot v1.1 Strict Profit Mode

Replace:
backend/main.py

Optional:
frontend/src/App.tsx

Redeploy Render. Vercel only if replacing App.tsx.

Test:
https://YOUR_RENDER_URL/strict-mode

This version is designed to stop holding weak red positions too long:
- stop-loss around -2.25%
- take-profit around +1.25%
- tighter trailing after +1%
- loser cooldown for 3 days
- max positions reduced to 6 where possible
