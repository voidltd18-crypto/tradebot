"""Opt-in, profit-threshold-only crypto limit SELL worker.

Never market-sells, stop-losses, or buys. A limit order can remain unfilled.
Estimated profit is not guaranteed once actual broker fees are applied.
"""
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_UP
from pathlib import Path

_ENABLED = "TRADEBOT_CRYPTO_PROFIT_SELL_ENABLED"
_MUTEX = threading.Lock()


def _positive(v):
    try:
        x = Decimal(str(v))
        return x if x.is_finite() and x > 0 else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def decide_limit_sell(*, entry, qty, bid, quoted_at, now=None,
                      min_gain_pct=Decimal("2.0"), cost_buffer_pct=Decimal("1.0")):
    """Pure fail-closed decision. Profit threshold includes a conservative cost cushion."""
    now = now or datetime.now(timezone.utc)
    entry, qty, bid = map(_positive, (entry, qty, bid))
    gain, buffer = _positive(min_gain_pct), _positive(cost_buffer_pct)
    if any(v is None for v in (entry, qty, bid, gain, buffer)):
        return {"eligible": False, "reason": "missing price/size/cost parameters"}
    if gain < buffer or gain > Decimal("30") or buffer < Decimal("0.5"):
        return {"eligible": False, "reason": "risk parameters outside safe bounds"}
    if quoted_at is None or quoted_at.tzinfo is None or quoted_at.utcoffset() is None:
        return {"eligible": False, "reason": "bid timestamp unverified"}
    age = (now - quoted_at.astimezone(timezone.utc)).total_seconds()
    if not (0 <= age <= 30):
        return {"eligible": False, "reason": "bid stale or future-dated"}
    # Limit floor covers configured estimated round-trip fees and margin.
    target = entry * (1 + gain / 100)
    if bid < target:
        return {"eligible": False, "reason": "live bid below target"}
    limit = target.quantize(Decimal("0.00000001"), rounding=ROUND_UP)
    return {"eligible": True, "limit": str(limit), "quantity": str(qty),
            "estimatedMarginPct": str(gain - buffer), "reason": "target reached at fresh bid"}


def _reserve(db_path, key):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=20) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS v19_crypto_auto_sell_attempts (
            position_key TEXT PRIMARY KEY, client_order_id TEXT NOT NULL,
            attempted_at TEXT NOT NULL, status TEXT NOT NULL
        )""")
        oid = "tbprofit-" + uuid.uuid4().hex[:24]
        inserted = conn.execute("INSERT OR IGNORE INTO v19_crypto_auto_sell_attempts VALUES (?,?,?,?)",
                                (key, oid, datetime.now(timezone.utc).isoformat(), "reserved")).rowcount
        return oid if inserted else None


def _submitted(db_path, key):
    with sqlite3.connect(db_path, timeout=20) as conn:
        conn.execute("UPDATE v19_crypto_auto_sell_attempts SET status='submitted' WHERE position_key=?", (key,))


def poll_profit_sells(client, data_client, db_path, *, now=None, enabled=False,
                      allowed_symbols=(), min_gain_pct="2", cost_buffer_pct="1"):
    """One broker pass; caller must explicitly opt into symbols and live mode."""
    result = {"enabled": enabled, "submitted": [], "blocked": []}
    if not enabled:
        return result
    if not _MUTEX.acquire(blocking=False):
        return result
    try:
        from alpaca.trading.requests import GetOrdersRequest, LimitOrderRequest
        from alpaca.trading.enums import QueryOrderStatus, OrderSide, TimeInForce
        from alpaca.data.requests import CryptoLatestQuoteRequest

        # A failed broker inventory lookup stops the whole polling cycle.
        positions = client.get_all_positions()
        pending = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        pending_symbols = {str(getattr(o, "symbol", "")).upper().replace("/", "") for o in pending}
        permitted = {x.upper().replace("/", "") for x in allowed_symbols}
        for pos in positions:
            symbol = str(getattr(pos, "symbol", "")).upper().replace("/", "")
            if symbol not in permitted or not symbol.endswith("USD"):
                continue
            if "crypto" not in str(getattr(pos, "asset_class", "")).lower():
                continue
            if symbol in pending_symbols:
                result["blocked"].append((symbol, "open broker order"))
                continue
            qty = _positive(getattr(pos, "qty", None))
            entry = _positive(getattr(pos, "avg_entry_price", None))
            if qty is None or entry is None:
                result["blocked"].append((symbol, "invalid broker position"))
                continue
            pair = symbol[:-3] + "/USD"
            quotes = data_client.get_crypto_latest_quote(CryptoLatestQuoteRequest(symbol_or_symbols=pair))
            quote = quotes.get(pair) if isinstance(quotes, dict) else None
            bid = getattr(quote, "bid_price", None)
            stamp = getattr(quote, "timestamp", None)
            outcome = decide_limit_sell(entry=entry, qty=qty, bid=bid, quoted_at=stamp,
                                        now=now, min_gain_pct=min_gain_pct,
                                        cost_buffer_pct=cost_buffer_pct)
            if not outcome["eligible"]:
                result["blocked"].append((symbol, outcome["reason"]))
                continue
            identity = f"{symbol}:{entry}:{qty}"
            oid = _reserve(db_path, identity)
            if not oid:
                result["blocked"].append((symbol, "previous sell attempt exists"))
                continue
            try:
                client.submit_order(LimitOrderRequest(
                    symbol=pair, qty=float(qty), side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC,
                    limit_price=float(Decimal(outcome["limit"])),
                    client_order_id=oid,
                ))
                _submitted(db_path, identity)
                result["submitted"].append(symbol)
            except Exception:
                # Ambiguous broker outcomes are NEVER retried automatically.
                result["blocked"].append((symbol, "broker submission failed/unknown; reserved"))
        return result
    finally:
        _MUTEX.release()


def install_worker(app, trading_client, api_key, api_secret, db_path):
    @app.on_event("startup")
    def _start():
        if os.getenv(_ENABLED, "").lower() != "true":
            return
        allowed = tuple(x.strip() for x in os.getenv("TRADEBOT_CRYPTO_PROFIT_SELL_SYMBOLS", "").split(",") if x.strip())
        if not allowed:
            print("CRYPTO PROFIT SELL | no explicitly approved symbols; disabled")
            return
        # Separate live approval, never infer from unrelated trading controls.
        if os.getenv("TRADEBOT_CRYPTO_PROFIT_SELL_LIVE_APPROVED", "").lower() != "true":
            print("CRYPTO PROFIT SELL | live approval missing; disabled")
            return
        from alpaca.data.historical import CryptoHistoricalDataClient
        data_client = CryptoHistoricalDataClient(api_key, api_secret)
        def run():
            while True:
                try:
                    outcome = poll_profit_sells(
                        trading_client, data_client, db_path, enabled=True,
                        allowed_symbols=allowed,
                        min_gain_pct=os.getenv("TRADEBOT_CRYPTO_PROFIT_SELL_GAIN_PCT", "2.0"),
                        cost_buffer_pct=os.getenv("TRADEBOT_CRYPTO_PROFIT_SELL_COST_BUFFER_PCT", "1.0"))
                    if outcome["submitted"]:
                        print("CRYPTO PROFIT SELL | submitted limit order for", ",".join(outcome["submitted"]))
                except Exception as e:
                    print("CRYPTO PROFIT SELL | failed safely:", type(e).__name__)
                time.sleep(60)
        threading.Thread(target=run, name="v19-crypto-profit-sell", daemon=True).start()
