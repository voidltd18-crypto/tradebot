# TradeBot V15.6 Database Hot-Path Fix

Fixes the remaining SQLite lock path identified in live logs.

## Root cause
Two different subsystems accidentally used the same function name `_v10_ensure_tables`.
The later human-promotion definition overwrote the research definition at runtime. As a result, V11 read endpoints repeatedly called `init_db()` and performed writes during normal dashboard reads.

## Changes
- Renamed the promotion initializer to `_v10_promotion_ensure_tables`.
- Updated promotion-only callers to use the renamed initializer.
- Restored V10 research callers to the correct V10 research initializer.
- Added once-per-process guarded initialization for V10 research tables.
- Added once-per-process guarded initialization for V11 discovery tables.
- Prevents Advisor, Strategy Intelligence and Weakness reads from repeatedly creating/updating schema rows.
- No trading, risk, order or strategy logic changed.
