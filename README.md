# Merged TradeBot Platform — Kraken Crypto + Alpaca Stocks

This package replaces the Binance crypto layer with Kraken, because Binance UK onboarding is currently unavailable for you.

## Render backend

Build command:

```bash
pip install -r backend/requirements.txt
```

Start command:

```bash
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

## Environment variables

```env
# Optional dashboard protection
DASHBOARD_API_KEY=choose_a_password

# Kraken crypto
KRAKEN_API_KEY=your_kraken_api_key
KRAKEN_SECRET_KEY=your_kraken_private_key

# Alpaca stocks
ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret

# Safe defaults
DRY_RUN=true
STOCK_NO_SAME_DAY_SELLS=true

# Crypto settings
CRYPTO_PAIRS=BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,ADA/USDT,LINK/USDT,DOGE/USDT,LTC/USDT
CRYPTO_POSITION_USDT=25
CRYPTO_MAX_POSITIONS=4
CRYPTO_CHECK_INTERVAL=15
```

## Endpoints

- `GET /status`
- `POST /start-crypto`
- `POST /stop-crypto`
- `POST /start-stock`
- `POST /stop-stock`
- `POST /stop-all`

## Safety

`DRY_RUN=true` means no real Kraken trades are sent. Keep this on first.
