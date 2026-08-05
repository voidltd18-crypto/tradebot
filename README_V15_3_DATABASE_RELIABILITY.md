# TradeBot V15.3 Database Reliability

This release keeps trading logic unchanged and fixes platform reliability.

## Changes

- SQLite WAL mode (`journal_mode=WAL`)
- `synchronous=NORMAL`
- 30-second SQLite busy timeout (configurable)
- Bounded exponential retry for locked reads, writes and commits
- Thread-safe SQLite connections
- WAL auto-checkpoint configuration
- Correct V12.1 Board worker startup flag
- Board thread named `v121-board-worker` to match the Operations watchdog

## Optional environment variables

- `SQLITE_BUSY_TIMEOUT_MS` default `30000`
- `SQLITE_LOCK_RETRIES` default `7`
- `SQLITE_RETRY_BASE_SECONDS` default `0.08`

Deploy by replacing the existing `backend` folder. The Render start command remains:

`uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
