TTWO stock search fix

Replace:
backend/main.py

What changed:
- TTWO added as Take-Two Interactive
- Search now tries exact ticker symbols directly through Alpaca even if not in universe
- This means typing TTWO, EA, etc. should return a preview card

Redeploy Render after replacing backend/main.py.
Vercel does not need redeploy unless you changed frontend too.
