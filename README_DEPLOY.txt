TradeBot V16.2.1 — AI Explainability

WHAT THIS FIXES
- Shows every scanner candidate in the AI Portfolio.
- Records QUALIFIED, WAITING, or REJECTED for each symbol.
- Shows the exact rejection/safety reason and all score inputs.
- Adds detailed V16 DECISION lines to Render logs.
- Does not lower thresholds or bypass PDT, position, open-order, daily lockout, cash, or risk safeguards.

DEPLOY BACKEND (RENDER)
Replace: backend/legacy/monolith.py

DEPLOY FRONTEND (VERCEL)
Replace the contents of your live frontend folder with the included frontend files, or at minimum replace:
frontend/src/pages/PortfolioPage.tsx
frontend/index.html

VERIFY
Render logs should show lines such as:
V16 DECISION | symbol=SOFI decision=REJECTED reason=SCORE_BELOW_MINIMUM ...
V16 DECISION | symbol=AMD decision=REJECTED reason=BUY_SAFETY_BLOCK ...
V16 DECISION | symbol=NVDA decision=QUALIFIED ...

The AI Portfolio page will show the same decisions in the AI Decision Inspector.
