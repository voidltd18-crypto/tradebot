import os

DASHBOARD_API_KEY = os.getenv('DASHBOARD_API_KEY', '')

# Global safety defaults
DRY_RUN = os.getenv('DRY_RUN', 'true').lower() == 'true'
CHECK_INTERVAL = int(os.getenv('CHECK_INTERVAL', '10'))

# Stock / Alpaca
STOCK_ENABLED = os.getenv('STOCK_ENABLED', 'true').lower() == 'true'
ALPACA_API_KEY = os.getenv('APCA_API_KEY_ID', '')
ALPACA_API_SECRET = os.getenv('APCA_API_SECRET_KEY', '')
ALPACA_PAPER = os.getenv('PAPER', 'true').lower() == 'true'
STOCK_NO_SAME_DAY_SELLS = os.getenv('STOCK_NO_SAME_DAY_SELLS', 'true').lower() == 'true'

# Crypto / Binance via CCXT
CRYPTO_ENABLED = os.getenv('CRYPTO_ENABLED', 'true').lower() == 'true'
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY', '')
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY', '')
BINANCE_TESTNET = os.getenv('BINANCE_TESTNET', 'true').lower() == 'true'

# Strategy defaults
FAST_STOP_LOSS_PCT = float(os.getenv('FAST_STOP_LOSS_PCT', '-1.0'))
TRAIL_START_PCT = float(os.getenv('TRAIL_START_PCT', '1.2'))
TRAIL_GIVEBACK_PCT = float(os.getenv('TRAIL_GIVEBACK_PCT', '0.7'))
PARTIAL_PROFIT_TRIGGER_PCT = float(os.getenv('PARTIAL_PROFIT_TRIGGER_PCT', '1.2'))
PARTIAL_PROFIT_SELL_PCT = float(os.getenv('PARTIAL_PROFIT_SELL_PCT', '0.35'))

STOCK_UNIVERSE = [s.strip().upper() for s in os.getenv(
    'STOCK_UNIVERSE',
    'NVDA,MSFT,AAPL,AMZN,META,GOOGL,AVGO,AMD,TSLA,PLTR,INTC,MU,UBER,PYPL,SHOP,COIN,CRM,NOW,SNOW,QCOM'
).split(',') if s.strip()]

CRYPTO_UNIVERSE = [s.strip().upper() for s in os.getenv(
    'CRYPTO_UNIVERSE',
    'BTC/USDT,ETH/USDT,SOL/USDT,BNB/USDT,XRP/USDT,ADA/USDT,AVAX/USDT,LINK/USDT,DOGE/USDT,LTC/USDT'
).split(',') if s.strip()]

STOCK_NOTIONAL_USD = float(os.getenv('STOCK_NOTIONAL_USD', '25'))
CRYPTO_NOTIONAL_USDT = float(os.getenv('CRYPTO_NOTIONAL_USDT', '25'))
