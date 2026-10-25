"""Guarded XRP post-sale dip limit-buy executor.

Disabled by default. Uses verified cash, fresh ask, last filled sell, and an
atomic SQLite sale-ID reservation. Never retries ambiguous broker outcomes.
"""
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

from backend.v19_reports_crypto_rebuy import available_crypto_cash
from backend.v19_xrp_repeat_cycle import assess_xrp_dip_entry
from backend.v19_xrp_repeat_cycle_snapshot import resolve_cycle_spend, _sym

_LOCK = threading.Lock()


def _reserve(db_path, sale_id):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=20) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS v19_xrp_cycle_orders (
            sale_id TEXT PRIMARY KEY, at TEXT NOT NULL, status TEXT NOT NULL)""")
        return db.execute("INSERT OR IGNORE INTO v19_xrp_cycle_orders VALUES (?,?,?)",
                          (sale_id, datetime.now(timezone.utc).isoformat(), "reserved")).rowcount == 1


def _mark(db_path, sale_id, status):
    with sqlite3.connect(db_path, timeout=20) as db:
        db.execute("UPDATE v19_xrp_cycle_orders SET status=? WHERE sale_id=?", (status, sale_id))


def cycle_once(client, data_client, db_path, *, configured_spend=None,
               pullback_pct="0.5", enabled=False, now=None):
    """At most one limit BUY attempt for each verified XRP sale fill."""
    if not enabled or configured_spend is None:
        return {"status": "disabled", "orderSubmitted": False}
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "orderSubmitted": False}
    try:
        from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest
        from alpaca.trading.enums import QueryOrderStatus, OrderSide, TimeInForce
        from alpaca.data.requests import CryptoLatestQuoteRequest
        positions = client.get_all_positions()
        pending = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        history = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500))
        candidates = [
            o for o in history
            if _sym(getattr(o, "symbol", "")) == "XRPUSD"
            and str(getattr(o, "side", "")).lower().split(".")[-1] == "sell"
            and str(getattr(o, "status", "")).lower().split(".")[-1] == "filled"
            and getattr(o, "filled_at", None) is not None
            and getattr(o, "filled_avg_price", None) is not None
            and getattr(o, "id", None) is not None
        ]
        if not candidates:
            return {"status": "no verified XRP sale", "orderSubmitted": False}
        latest = max(candidates, key=lambda order: order.filled_at)
        account = client.get_account()
        cash = available_crypto_cash(account)
        spend = resolve_cycle_spend(cash, configured_spend)
        quotes = data_client.get_crypto_latest_quote(
            CryptoLatestQuoteRequest(symbol_or_symbols="XRP/USD"))
        quote = quotes.get("XRP/USD") if isinstance(quotes, dict) else None
        if quote is None:
            return {"status": "quote missing", "orderSubmitted": False}
        eligibility = assess_xrp_dip_entry(
            ask=getattr(quote, "ask_price", None),
            ask_at=getattr(quote, "timestamp", None),
            positions=[getattr(p, "symbol", "") for p in positions],
            open_order_symbols=[getattr(o, "symbol", "") for o in pending],
            available_cash=cash, spend_usd=spend,
            last_sale_price=getattr(latest, "filled_avg_price", None),
            last_sale_at=getattr(latest, "filled_at", None),
            last_sale_filled=True, pullback_pct=pullback_pct, now=now,
        )
        if not eligibility["canEnter"]:
            return {"status": eligibility["reason"], "orderSubmitted": False}
        # Prevent a buy based on an old sale if more recent filled XRP orders exist.
        latest_sale_time = latest.filled_at
        for order in history:
            if (_sym(getattr(order, "symbol", "")) == "XRPUSD"
                and str(getattr(order, "status", "")).lower().split(".")[-1] == "filled"
                and getattr(order, "filled_at", None) is not None
                and getattr(order, "filled_at") > latest_sale_time):
                return {"status": "newer XRP trade exists", "orderSubmitted": False}
        # Decimal floor prevents exceeding spend even after quantity rounding.
        limit = Decimal(eligibility["targetAskAtMost"])
        qty = (Decimal(str(spend)) / limit).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        if qty <= 0 or qty * limit < Decimal("1"):
            return {"status": "quantity below minimum", "orderSubmitted": False}
        sale_id = str(latest.id)
        if not _reserve(db_path, sale_id):
            return {"status": "cycle already attempted", "orderSubmitted": False}
        from uuid import uuid5, NAMESPACE_URL
        client_id = "tbxrp-" + uuid5(NAMESPACE_URL, sale_id).hex[:24]
        try:
            order = client.submit_order(LimitOrderRequest(
                symbol="XRP/USD", qty=float(qty), side=OrderSide.BUY,
                time_in_force=TimeInForce.GTC, limit_price=float(limit),
                client_order_id=client_id,
            ))
            _mark(db_path, sale_id, "submitted")
            return {"status": "limit order submitted", "orderSubmitted": True,
                    "clientOrderId": client_id}
        except Exception:
            # Never retry a possibly accepted order after network failure.
            _mark(db_path, sale_id, "unknown; manual broker reconciliation required")
            return {"status": "broker outcome unknown; do not retry", "orderSubmitted": False}
    finally:
        _LOCK.release()


def install_cycle_worker(app, client, api_key, api_secret, db_path):
    @app.on_event("startup")
    def startup():
        if os.getenv("TRADEBOT_XRP_REPEAT_BUY_ENABLED", "").lower() != "true":
            return
        if os.getenv("TRADEBOT_XRP_REPEAT_BUY_LIVE_APPROVED", "").lower() != "true":
            return
        configured = os.getenv("TRADEBOT_XRP_REPEAT_SPEND_USD", "").strip()
        if not configured:
            return
        from alpaca.data.historical import CryptoHistoricalDataClient
        data = CryptoHistoricalDataClient(api_key, api_secret)
        def poll():
            while True:
                try:
                    result = cycle_once(client, data, db_path, configured_spend=configured,
                                        pullback_pct=os.getenv("TRADEBOT_XRP_REPEAT_PULLBACK_PCT", "0.5"),
                                        enabled=True)
                    if result["orderSubmitted"]:
                        print("XRP CYCLE | guarded limit buy submitted")
                except Exception as exc:
                    print("XRP CYCLE | polling error:", type(exc).__name__)
                time.sleep(60)
        threading.Thread(target=poll, name="v19-xrp-cycle", daemon=True).start()
