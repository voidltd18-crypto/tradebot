TradeBot V16.5.5 — Allocation Affordability Fix

Replace:
  backend/legacy/monolith.py

Fixes the conflict where V16 planned a smaller affordable allocation but the
legacy capacity pre-check demanded enough buying power for a full target-sized
position.

New behaviour:
- V16 checks structural position capacity before building the plan.
- The portfolio planner sizes from actual managed capital and buying power.
- Each planned allocation is checked against fresh live buying power immediately
  before order submission.
- Existing market-open, PDT, daily lock, open-order, holding, quality, spread,
  emergency-stop and minimum-order protections remain active.

Expected log when an affordable allocation submits:
  AUTO V16.5.5 PORTFOLIO #1 SCORE BUY $35.03 HOOD ...

Expected block if buying power changes before submission:
  V16 LIVE ORDER BLOCK | ... reason=ALLOCATION_EXCEEDS_BUYING_POWER
