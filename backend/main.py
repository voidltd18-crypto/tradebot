"""TradeBot FastAPI entry point.

V12.2 begins the safe modular migration without changing live behaviour.
The proven V12.1 application remains intact in ``backend.legacy.monolith``
while new services are extracted incrementally behind stable interfaces.

Render command remains:
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""
from backend.legacy.monolith import app

__all__ = ["app"]

# Read-only Telegram crypto alerts run only with explicit environment opt-in.
from backend.legacy import monolith as _legacy
from backend.v19_crypto_telegram_monitor import install_crypto_telegram_worker
install_crypto_telegram_worker(app, _legacy.trading_client, _legacy.state, _legacy.SQLITE_DB_FILE)


from fastapi import Request
from backend.v19_crypto_telegram_monitor import crypto_monitor_status

@app.get("/v19/telegram-crypto-monitor-status")
def telegram_crypto_monitor_status(request: Request):
    _legacy.verify_api_key(request)
    return crypto_monitor_status(_legacy.SQLITE_DB_FILE)
