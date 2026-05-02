# Merged Tradebot Platform

One backend/site for both bots:

- **Stocks engine**: Alpaca, PDT-safe swing mode by default.
- **Crypto engine**: Binance Spot via CCXT, testnet/dry-run by default.
- **Shared strategy**: sniper-style entries, hard stop, trailing exit.

## Safe defaults

```env
DRY_RUN=true
BINANCE_TESTNET=true
STOCK_NO_SAME_DAY_SELLS=true
```

This means no real orders are sent unless you deliberately change those values.

## Render start command

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

## Environment variables

```env
DASHBOARD_API_KEY=your_dashboard_password

# Alpaca stocks
STOCK_ENABLED=true
APCA_API_KEY_ID=your_alpaca_key
APCA_API_SECRET_KEY=your_alpaca_secret
PAPER=true
STOCK_NO_SAME_DAY_SELLS=true

# Binance crypto
CRYPTO_ENABLED=true
BINANCE_API_KEY=your_binance_key
BINANCE_SECRET_KEY=your_binance_secret
BINANCE_TESTNET=true

# Global safety
DRY_RUN=true
CHECK_INTERVAL=10
FAST_STOP_LOSS_PCT=-1.0
TRAIL_START_PCT=1.2
TRAIL_GIVEBACK_PCT=0.7
```

## Endpoints

```text
GET  /status
POST /engines/stocks/start
POST /engines/stocks/pause
POST /engines/crypto/start
POST /engines/crypto/pause
POST /start-all
POST /pause-all
```

Use the `x-api-key` header if `DASHBOARD_API_KEY` is configured.
