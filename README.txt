TradeBot V16.5.2 — Portfolio Live Execution

Replace:
  backend/legacy/monolith.py

What changed:
- V16 portfolio score is now the live entry gate when AI Portfolio Manager is enabled.
- The old Sniper/A+ confidence and quality gates remain visible as supporting evidence but no longer veto V16-qualified candidates.
- Full safeguards remain: market open, emergency stop, bot enabled, PDT daily buy limit, position capacity, buying power, existing holdings, open orders, daily symbol locks, minimum order size, and hard spread limit.
- Set V16_PORTFOLIO_EXECUTION_ENABLED=false to return to legacy Sniper/A+ execution.
- Set V16_PORTFOLIO_REQUIRE_READY_TRIGGER=true to additionally require the old dip trigger.

Expected Render log after an order:
  AUTO V16.5 PORTFOLIO #1 SCORE BUY $... SYMBOL score=...
