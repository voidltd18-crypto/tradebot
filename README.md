# A+ Trade Quality Gate Package

This is a focused money-making upgrade.

## What it adds
- A+ Trade Quality Gate
- Blocks low-confidence manual Money Buy
- Requires confidence >= 0.70
- Requires stronger quality score
- Requires tighter spread
- Requires non-negative momentum
- Temporary loser blacklist after repeat losses

## Why
Trade less, only take better setups, and stop feeding weak tickers.

## Render
Build:
pip install -r backend/requirements.txt

Start:
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
