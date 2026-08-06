TradeBot V16.5.1 — Real Market Factor Source Fix

Replace on Render:
  backend/legacy/monolith.py

Fixes:
- Qualified rows now return rawPortfolioScore correctly.
- Momentum uses cached Alpaca 1-minute bars while the live curve warms up after restart.
- Relative-strength value 0.00 is no longer incorrectly replaced by neutral 0.50.
- Saved plans from older scoring engines are automatically rebuilt.
- Factor payload reports marketDataSource and historicalSource for verification.
- Duplicate factor fields removed from decision payloads.

Verification after deploy:
- /v16/portfolio/status should contain:
  scoringEngineVersion: V16.5.1-REAL-MARKET-FACTORS
- decisions[*].rawPortfolioScore should differ from portfolioScore when calibration applies.
- decisions[*].factors.marketDataSource should normally be ALPACA_1MIN_BARS immediately after restart, then LIVE_CURVE after enough scan cycles.
- Relative strength should span the batch rather than remaining near 0.50 for every symbol.
