Defensive Profit Safe Patch

This package does NOT remove unrelated features.
It preserves the existing dashboard/frontend and only patches backend trading/risk behaviour.

Changed in backend/main.py only:
1. Strict mode is now connected to the live sell flow.
2. Loser cooldown and quality-only blocked tickers are now checked before buys.
3. One-position mode is capped by ONE_POSITION_MAX_EQUITY_PCT, default 45%.
4. Confidence sizing remains active even in one-position mode.
5. Dynamic market scanner default refresh is 45 minutes instead of 4 hours.
6. New defensive market filter uses QQQ momentum before new buys.
7. New bounce confirmation reduces falling-knife dip buys.
8. Status payload now exposes the new defensive settings/reasons.

Unchanged:
- Login/auth routes
- Dashboard UI file App.tsx
- Manual buy/sell routes
- Banking/trading cap routes
- Backfill/reporting routes
- Baseline/report routes
- Manual universe routes
- Existing analytics/stock memory/SQLite code

Deploy method:
Extract this zip and upload the contents to GitHub, replacing matching files.
