TradeBot V16.3 — Adaptive Scoring Calibration

This update keeps the absolute score dominant, adds bounded batch calibration, and permits a small adaptive threshold only when the market produces too few candidates. The threshold cannot fall below 0.520 by default. Existing PDT, buy lockouts, position limits, cash reserves, holdings checks and order limits remain active.

Deploy:
- Render: backend/legacy/monolith.py
- Vercel: frontend/src/pages/PortfolioPage.tsx

Optional Render environment variables:
AI_PORTFOLIO_ADAPTIVE_SCORE_ENABLED=true
AI_PORTFOLIO_ADAPTIVE_SCORE_FLOOR=0.52
AI_PORTFOLIO_ADAPTIVE_TARGET_COUNT=2
AI_PORTFOLIO_RELATIVE_SCORE_WEIGHT=0.22
