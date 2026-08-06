TradeBot V16.5.3 — Portfolio Quality Guard

Replace:
  backend/legacy/monolith.py

Purpose:
- Keeps V16 portfolio-score live execution enabled.
- Prevents batch calibration alone from promoting a weak setup into a live order.
- Adds a second identical quality check immediately before order submission.

Automatic live-entry defaults:
- calibrated portfolio score must meet the active portfolio threshold
- raw score must be at least 0.560
- underlying scanner quality must be at least 0.0060
- liquidity factor must be at least 0.450
- preferred execution spread must be no more than 0.0100
- absolute spread ceiling remains unchanged
- all existing PDT, daily lock, open-order, holding, capacity, cash and emergency protections remain active

Optional Render environment variables:
  V16_PORTFOLIO_MIN_RAW_SCORE=0.56
  V16_PORTFOLIO_MIN_QUALITY=0.006
  V16_PORTFOLIO_MIN_LIQUIDITY_FACTOR=0.45
  V16_PORTFOLIO_EXECUTION_MAX_SPREAD=0.010

Expected rejection log examples:
  reason=UNDERLYING_QUALITY_TOO_LOW
  reason=RAW_SCORE_TOO_LOW
  reason=EXECUTION_SPREAD_TOO_WIDE
  reason=LIQUIDITY_FACTOR_TOO_LOW
