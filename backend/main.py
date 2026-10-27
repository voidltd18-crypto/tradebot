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


# Manual Reports crypto re-buy. OFF by default; stock/automatic trading untouched.
from fastapi import Body
from backend.v19_reports_crypto_rebuy import rebuy_order, enabled as rebuy_enabled, crypto_rebuy_preview

@app.get("/v19/reports/crypto-buy-again/available")
def reports_crypto_buy_again_available(request: Request):
    _legacy.verify_api_key(request)
    if not rebuy_enabled():
        return {"ok": False, "canBuy": False, "availableUsd": None,
                "message": "Buy Again is disabled"}
    return crypto_rebuy_preview(_legacy.trading_client)


@app.post("/v19/reports/crypto-buy-again")
def reports_crypto_buy_again(request: Request, payload: dict = Body(...)):
    _legacy.verify_api_key(request)
    if not rebuy_enabled():
        return {"ok": False, "orderSubmitted": False,
                "message": "Buy Again is not enabled yet. No order placed."}
    # Verify symbol against authoritative closed trade history, not browser input.
    symbol = str(payload.get("symbol", "")).strip().upper()
    history = _legacy.closed_trades_from_db(5000)
    allowed = {str(row.get("symbol", "")).strip().upper() for row in history
               if str(row.get("symbol", "")).strip().upper() == symbol
               and float(row.get("qty") or 0) > 0}
    return rebuy_order(
        _legacy.trading_client,
        symbol=symbol, amount=payload.get("amountUsd"),
        confirmation=payload.get("confirmation"), allowed_ids=allowed,
        request_id=payload.get("requestId"), db_path=_legacy.SQLITE_DB_FILE,
        enabled=True,
        is_paper=_legacy.PAPER,
        allow_live=__import__("os").environ.get("TRADEBOT_REPORTS_CRYPTO_REBUY_LIVE_ENABLED", "").lower() == "true",
    )


# Crypto profit-only LIMIT exits: separate explicit live opt-in; no stop-loss orders.
from backend.v19_crypto_profit_sell_executor import install_worker as install_crypto_profit_sell_worker
install_crypto_profit_sell_worker(
    app, _legacy.trading_client, _legacy.API_KEY, _legacy.API_SECRET, _legacy.SQLITE_DB_FILE
)


# XRP post-sale dynamic-dip eligibility. Read-only; NEVER submits buys.
@app.get("/v19/xrp-repeat-cycle-preview")
def xrp_repeat_cycle_preview(request: Request):
    _legacy.verify_api_key(request)
    import os
    from alpaca.data.historical import CryptoHistoricalDataClient
    from backend.v19_xrp_repeat_cycle_snapshot import xrp_cycle_preview
    limit = os.getenv("TRADEBOT_XRP_REPEAT_SPEND_USD", "").strip()
    if not limit:
        return {"readOnly": True, "canEnter": False, "action": "HOLD",
                "reason": "per-cycle USD spending limit not configured"}
    data_client = CryptoHistoricalDataClient(_legacy.API_KEY, _legacy.API_SECRET)
    return xrp_cycle_preview(
        _legacy.trading_client, data_client,
        spend_usd=limit,
        pullback_pct=os.getenv("TRADEBOT_XRP_REPEAT_PULLBACK_PCT", "0.5"),
        cooldown_minutes=30,
    )

from backend.v19_xrp_cycle_executor import install_cycle_worker
install_cycle_worker(app, _legacy.trading_client, _legacy.API_KEY, _legacy.API_SECRET, _legacy.SQLITE_DB_FILE)


# Authenticated, read-only proof of automatic sell worker polling.
from backend.v19_crypto_profit_sell_executor import worker_health as crypto_profit_sell_health

@app.get("/v19/crypto-profit-sell-health")
def crypto_profit_sell_health_endpoint(request: Request):
    _legacy.verify_api_key(request)
    return crypto_profit_sell_health(_legacy.SQLITE_DB_FILE)


# Universal crypto repeat-cycle worker (disabled unless separately approved).
# First entry remains manual; verified profitable sells can arm per-symbol dip re-buys.
from backend.v19_universal_crypto_cycle_executor import install_universal_cycle_worker
install_universal_cycle_worker(
    app, _legacy.trading_client, _legacy.API_KEY, _legacy.API_SECRET, _legacy.SQLITE_DB_FILE
)
