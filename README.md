# Phase 2 — 20 Stock Full Proper Package

This is the proper full package, not the 3-file fallback.

Includes all previous bot features plus:
- Weekly Auto Universe increased to 20 stocks
- Max positions increased to 20
- Stricter entry filter
- Early loss cut
- Dynamic slot sizing for 20-stock mode
- Winner boost
- Dashboard Phase 2 panel
- Existing SQLite, Alpaca backfill, PnL matching, GBP conversion, Stock Memory, optimiser, and safe one-cycle-per-stock behavior retained

Important:
The bot watches 20 stocks but does NOT blindly buy all 20.
It only buys symbols that pass confidence, quality, spread, momentum, cooldown, and risk filters.

Render:
Build: pip install -r backend/requirements.txt
Start: uvicorn backend.main:app --host 0.0.0.0 --port $PORT
