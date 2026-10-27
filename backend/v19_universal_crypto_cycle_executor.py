"""Guarded Universal crypto post-sale dip limit-buy executor.

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
from backend.v19_crypto_repeat_cycle import assess_crypto_dip_entry
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


def _is_confirmed_tradebot_profit_sale(order, symbol):
    """Only a filled sell from this bot's approved profit seller can arm XRP."""
    return (
        _sym(getattr(order, "symbol", "")) == symbol
        and str(getattr(order, "side", "")).lower().split(".")[-1] == "sell"
        and str(getattr(order, "status", "")).lower().split(".")[-1] == "filled"
        and str(getattr(order, "client_order_id", "")).startswith("tbprofit-")
        and getattr(order, "filled_at", None) is not None
        and getattr(order, "filled_avg_price", None) is not None
        and getattr(order, "id", None) is not None
    )


def cycle_once(client, data_client, db_path, *, symbol, configured_spend=None,
               pullback_pct="0.5", enabled=False, now=None, trading_allowed=True):
    """At most one limit BUY attempt for each verified crypto sale fill."""
    symbol = _sym(symbol)
    if not (symbol.endswith("USD") and symbol[:-3].isalpha() and 2 <= len(symbol[:-3]) <= 10):
        return {"status": "invalid crypto symbol", "orderSubmitted": False}
    if not enabled or configured_spend is None:
        return {"status": "disabled", "orderSubmitted": False}
    if not trading_allowed:
        return {"status": "paused or manual override active", "orderSubmitted": False}
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "orderSubmitted": False}
    try:
        from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest
        from alpaca.trading.enums import QueryOrderStatus, OrderSide, TimeInForce
        from alpaca.data.requests import CryptoLatestQuoteRequest
        # A shared crypto account must not pyramid into other pairs by default.
        # This guard deliberately checks all broker crypto positions and open BUY orders.
        positions = client.get_all_positions()
        if any("crypto" in str(getattr(p, "asset_class", "")).lower()
               and _sym(getattr(p, "symbol", "")) != symbol
               for p in positions):
            return {"status": "another crypto position already held", "orderSubmitted": False}
        pending = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        if any(str(getattr(o, "side", "")).lower().split(".")[-1] == "buy"
               and _sym(getattr(o, "symbol", "")) != symbol
               and _sym(getattr(o, "symbol", "")).endswith("USD") for o in pending):
            return {"status": "another crypto buy order pending", "orderSubmitted": False}
        history = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.CLOSED, limit=500))
        candidates = [o for o in history if _is_confirmed_tradebot_profit_sale(o, symbol)]
        if not candidates:
            return {"status": "no confirmed TradeBot crypto profit-sale fill", "orderSubmitted": False}
        latest = max(candidates, key=lambda order: order.filled_at)
        account = client.get_account()
        cash = available_crypto_cash(account)
        spend = resolve_cycle_spend(cash, configured_spend)
        pair = symbol[:-3] + "/USD"
        quotes = data_client.get_crypto_latest_quote(
            CryptoLatestQuoteRequest(symbol_or_symbols=pair))
        quote = quotes.get(pair) if isinstance(quotes, dict) else None
        if quote is None:
            return {"status": "quote missing", "orderSubmitted": False}
        eligibility = assess_crypto_dip_entry(
            symbol=symbol,
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
        # Prevent a buy based on an old sale if more recent filled crypto orders exist.
        latest_sale_time = latest.filled_at
        for order in history:
            if (_sym(getattr(order, "symbol", "")) == symbol
                and str(getattr(order, "status", "")).lower().split(".")[-1] == "filled"
                and getattr(order, "filled_at", None) is not None
                and getattr(order, "filled_at") > latest_sale_time):
                return {"status": "newer crypto trade exists", "orderSubmitted": False}
        # Decimal floor prevents exceeding spend even after quantity rounding.
        limit = Decimal(eligibility["targetAskAtMost"])
        qty = (Decimal(str(spend)) / limit).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
        if qty <= 0 or qty * limit < Decimal("1"):
            return {"status": "quantity below minimum", "orderSubmitted": False}
        sale_id = str(latest.id)
        if not _reserve(db_path, sale_id):
            return {"status": "cycle already attempted", "orderSubmitted": False}
        from uuid import uuid5, NAMESPACE_URL
        client_id = "tbcycle-" + uuid5(NAMESPACE_URL, sale_id).hex[:24]
        try:
            order = client.submit_order(LimitOrderRequest(
                symbol=pair, qty=float(qty), side=OrderSide.BUY,
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



def install_universal_cycle_worker(app, client, api_key, api_secret, db_path):
    """Live execution is off unless separately opted in and explicitly approved."""
    @app.on_event("startup")
    def startup():
        if os.getenv("TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_ENABLED", "").lower() != "true":
            return
        if os.getenv("TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_LIVE_APPROVED", "").lower() != "true":
            return
        approved = { _sym(x.strip()) for x in os.getenv("TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_SYMBOLS", "").split(",") if x.strip() }
        if not approved:
            return
        configured = os.getenv("TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_SPEND_USD", "").strip()
        if not configured:
            return
        # Never run a parallel XRP worker for the same symbol.
        if os.getenv("TRADEBOT_XRP_REPEAT_BUY_ENABLED", "").lower() == "true":
            approved.discard("XRPUSD")
        approved = sorted(s for s in approved if s.endswith("USD") and s[:-3].isalpha()
                          and 2 <= len(s[:-3]) <= 10)
        if not approved:
            return
        from alpaca.data.historical import CryptoHistoricalDataClient
        from backend.legacy import monolith as legacy
        data = CryptoHistoricalDataClient(api_key, api_secret)

        def poll():
            while True:
                try:
                    allowed = (bool(getattr(legacy, "bot_enabled", False))
                               and not bool(getattr(legacy, "emergency_stop", True))
                               and not bool(getattr(legacy, "manual_override", True)))
                    if allowed:
                        for sym in approved:
                            result = cycle_once(
                                client, data, db_path, symbol=sym, configured_spend=configured,
                                pullback_pct=os.getenv("TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_PULLBACK_PCT", "0.5"),
                                enabled=True, trading_allowed=allowed,
                            )
                            if result["orderSubmitted"]:
                                print("UNIVERSAL CRYPTO CYCLE | guarded limit buy submitted for", sym)
                except Exception as exc:
                    print("UNIVERSAL CRYPTO CYCLE | polling error:", type(exc).__name__)
                time.sleep(60)
        threading.Thread(target=poll, name="v19-universal-crypto-cycle", daemon=True).start()
