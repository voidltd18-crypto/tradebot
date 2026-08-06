TradeBot V16.4 Multi-Factor Portfolio Intelligence

Deploy both parts:
1. Render: replace backend/legacy/monolith.py
2. Vercel: replace frontend/src/pages/PortfolioPage.tsx

Changes:
- Six-factor transparent scoring
- Momentum, relative strength, liquidity, volatility quality, historical edge, regime fit
- Existing calibrated batch ranking retained
- Decision Inspector displays every factor
- No PDT, lockout, cash, position or order safeguards bypassed
