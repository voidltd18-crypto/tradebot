TradeBot V16.5 REAL MARKET FACTORS

BACKEND: replace backend/legacy/monolith.py and deploy to Render.
FRONTEND: replace frontend/src/pages/PortfolioPage.tsx and deploy to Vercel.

Changes:
- Momentum uses the live per-symbol price curve (return, slope, directional consistency).
- Relative strength is measured against the other candidates in the same scan batch.
- Liquidity uses the live spread and relative volume when available.
- Volatility quality uses realised curve volatility and drawdown.
- Historical edge uses the existing Symbol Reputation engine when sample data exists.
- Regime fit uses the existing market-regime detector.
- Existing PDT, lockout, holding, open-order, cash and position safety controls are unchanged.
