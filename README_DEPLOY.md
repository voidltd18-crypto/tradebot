# TradeBot V12.2 — Safe Modular Backend Foundation

This package preserves the complete deployed V12.1 AI CEO + AI Board runtime
and changes only the code layout.

## Deploy

Replace the existing `backend` folder with the included `backend` folder.
Keep the Render start command unchanged:

```text
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

## What changed

- `backend/main.py` is now a tiny stable entry point.
- The proven full runtime is in `backend/legacy/monolith.py`.
- Explicit service boundaries now exist for CEO, Board, Evolution, Research,
  Reputation, Execution, Risk and Memory.
- No endpoint names, database tables, environment variables, workers,
  safeguards, or trading behaviour were changed.

## Why this is staged

Moving 600k+ of tightly connected live trading code in one pass would create
unnecessary deployment and financial risk. V12.2 establishes a deployable,
rollback-safe modular foundation. Each subsystem can now be extracted and
verified separately while the public API remains stable.

## Verification

Run locally from the project root:

```bash
python -m py_compile backend/main.py backend/legacy/monolith.py
python tests/validate_structure.py
```

The full runtime import requires the project dependencies from `requirements.txt` (including Alpaca). After deployment, verify the existing protected endpoints, especially:

```text
/status
/v12/ceo/status
/v12/board/status
```
