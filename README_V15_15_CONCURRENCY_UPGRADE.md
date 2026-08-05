# TradeBot V15.15 — SQLite Concurrency Upgrade

## Changes

- Keeps SQLite in WAL mode with NORMAL synchronous mode and busy timeout.
- Adds a process-wide serialized writer lock. A connection acquires it on its first mutating SQL statement and releases it on commit, rollback or close.
- Retains bounded retry with jitter for transient SQLite locks.
- Makes V10 Operator schema initialization startup-only and idempotent.
- Makes `/v10/operator/status` read-only.
- Adds last-known-good fallback for Operator status during brief database contention.
- Adds a 45-second Reports payload cache.
- Makes `/reports` return the last known-good snapshot if SQLite is temporarily busy.
- Preserves all trading, risk, AI, position-capacity and adaptive-threshold logic.

## Deploy

Upload the complete backend folder, then deploy Render with the existing command:

`uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

No frontend change is required.

## Validation

After deployment, check:

- `/v10/operator/status`
- `/reports`
- `/v15/operations/engine-health`

The Operator and Reports entries should clear on the next Operations audit.
