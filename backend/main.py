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
from backend.config import CRYPTO_ENABLED
from backend.legacy import monolith as _legacy
from backend.v19_stock_crypto_capacity import install_stock_crypto_capacity
install_stock_crypto_capacity(_legacy)
from backend.v19_crypto_telegram_monitor import install_crypto_telegram_worker
if CRYPTO_ENABLED:
    install_crypto_telegram_worker(app, _legacy.trading_client, _legacy.state, _legacy.SQLITE_DB_FILE)


from fastapi import HTTPException, Request
from backend.v19_crypto_telegram_monitor import crypto_monitor_status

@app.get("/v19/telegram-crypto-monitor-status")
def telegram_crypto_monitor_status(request: Request):
    _legacy.verify_api_key(request)
    return crypto_monitor_status(_legacy.SQLITE_DB_FILE)


# Stable Reports endpoints tell the existing dashboard that order entry is disabled.
@app.get("/v19/reports/crypto-buy-again/available")
def reports_crypto_buy_again_available(request: Request):
    _legacy.verify_api_key(request)
    return {"ok": False, "canBuy": False, "availableUsd": None,
            "message": "TradeBot is read-only. Orders are disabled."}


@app.post("/v19/reports/crypto-buy-again")
def reports_crypto_buy_again(request: Request):
    _legacy.verify_api_key(request)
    return {"ok": False, "orderSubmitted": False,
            "message": "TradeBot is read-only. Orders are disabled."}


# XRP post-sale dynamic-dip eligibility. Read-only; NEVER submits buys.
@app.get("/v19/xrp-repeat-cycle-preview")
def xrp_repeat_cycle_preview(request: Request):
    _legacy.verify_api_key(request)
    if not CRYPTO_ENABLED:
        raise HTTPException(403, "Crypto monitoring is disabled.")
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

# Authenticated, read-only proof of automatic sell worker polling.
from backend.v19_crypto_profit_sell_executor import worker_health as crypto_profit_sell_health

@app.get("/v19/crypto-profit-sell-health")
def crypto_profit_sell_health_endpoint(request: Request):
    _legacy.verify_api_key(request)
    return crypto_profit_sell_health(_legacy.SQLITE_DB_FILE)


# Verify both watchlist names against the existing Alpaca account on startup.
# Read-only asset lookup: no orders, no changes to existing mode/credentials.
from backend.v19_two_stock_asset_preflight import check_from_broker as _two_stock_asset_probe

@app.on_event("startup")
def probe_two_stock_assets():
    for symbol in ("TSLA", "SPCX"):
        result = _two_stock_asset_probe(_legacy.trading_client, symbol)
        print(
            "V19 TWO STOCK ALPACA PREFLIGHT | symbol=%s eligible=%s issuer=%s reasons=%s"
            % (
                symbol,
                result["eligible"],
                result.get("brokerName", "unavailable"),
                ",".join(result["reasons"]) or "none",
            ),
            flush=True,
        )

# Read-only manual crypto rebuy preview. Never places orders.
from backend.v19_manual_crypto_rebuy_preview import preview as manual_crypto_rebuy_preview

@app.get("/v19/manual-crypto-rebuy-preview/{symbol}")
def manual_crypto_rebuy_preview_endpoint(symbol: str, request: Request):
    _legacy.verify_api_key(request)
    if not CRYPTO_ENABLED:
        raise HTTPException(403, "Crypto monitoring is disabled.")
    from alpaca.data.historical import CryptoHistoricalDataClient
    data_client = CryptoHistoricalDataClient(_legacy.API_KEY, _legacy.API_SECRET)
    return manual_crypto_rebuy_preview(_legacy.trading_client, data_client, symbol)


@app.get("/v19/manual-crypto-rebuy-scan")
def manual_crypto_rebuy_scan_endpoint(request: Request):
    _legacy.verify_api_key(request)
    if not CRYPTO_ENABLED:
        raise HTTPException(403, "Crypto monitoring is disabled.")
    from alpaca.data.historical import CryptoHistoricalDataClient
    from backend.v19_manual_crypto_rebuy_bulk import scan_all
    data_client = CryptoHistoricalDataClient(_legacy.API_KEY, _legacy.API_SECRET)
    return scan_all(_legacy.trading_client, data_client)


@app.on_event("startup")
def start_stock_broker_audit():
    """Run a read-only check once per service start and log aggregate results."""
    from threading import Thread
    Thread(target=_stock_broker_audit, daemon=True, name="stock-broker-audit").start()


def _stock_broker_audit():
    from backend.stock_broker_state import BrokerStateUnverified, broker_failure_category, stock_account
    from backend.stock_ownership import reconcile_stock_intents

    broker = _legacy.trading_client
    try:
        account = broker.get_account()
        try:
            stock_account(broker)
            account_check = "active"
        except BrokerStateUnverified as exc:
            account_check = str(exc)
        positions = broker.get_all_positions()
        orders = broker.get("/orders", data={"status": "open", "limit": 500})
        if not isinstance(positions, list) or not isinstance(orders, list):
            raise ValueError("malformed broker response")
        equity_positions = [
            position for position in positions
            if getattr(position.asset_class, "value", position.asset_class) == "us_equity"
        ]
        for position in equity_positions:
            qty = float(position.qty)
            value = abs(float(position.market_value))
            classification = ("nonpositive quantity" if qty <= 0 else "sub-cent residue"
                              if value < _legacy.POSITION_DUST_VALUE_USD else "active")
            print(f"STOCK POSITION AUDIT | symbol={position.symbol} qty={position.qty} "
                  f"available={position.qty_available} category={classification}", flush=True)
        sellable_reported = sum(getattr(position, "qty_available", None) is not None for position in equity_positions)
        report = reconcile_stock_intents(_legacy.db_connect, broker, account)
        print(
            f"STOCK BROKER AUDIT | account={account_check} stock_positions={len(equity_positions)} "
            f"sellable_reported={sellable_reported} open_orders={len(orders)} "
            f"open_orders_complete={len(orders) < 500} ledger={report}", flush=True,
        )
        recent = broker.get("/account/activities", data={"activity_types": "FILL", "page_size": 1})
        visible = isinstance(recent, list) and bool(recent) and all(
            isinstance(row, dict) and row.get("activity_type") == "FILL" and row.get("order_id") and row.get("id")
            for row in recent)
        print(f"STOCK FILL VISIBILITY | observed={bool(visible)}", flush=True)
    except BrokerStateUnverified as exc:
        print(f"STOCK BROKER AUDIT | {exc}", flush=True)
    except Exception as exc:
        print(f"STOCK BROKER AUDIT | unverified ({broker_failure_category(exc)})", flush=True)
