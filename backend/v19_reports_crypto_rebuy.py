"""Manually confirmed Alpaca crypto re-buy, fail-closed and disabled by default.

Orders are never retried automatically. Persistent request IDs make repeated
submissions safe across browser retries and Render process restarts.
"""
import os
import re
import sqlite3
import threading
import uuid
from decimal import Decimal, InvalidOperation

_REBUY_LOCK = threading.Lock()
_SYMBOL = re.compile(r"^[A-Z0-9]{2,20}/USD$")


def parse_request(symbol, amount, confirmation):
    sym = str(symbol or "").strip().upper()
    if not _SYMBOL.fullmatch(sym):
        raise ValueError("Only USD crypto pairs from closed trades are eligible")
    if str(confirmation or "") != f"BUY {sym}":
        raise ValueError("Exact confirmation required")
    try:
        spend = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid USD spend") from None
    if not spend.is_finite() or not (Decimal("1") <= spend <= Decimal("250")):
        raise ValueError("USD spend must be between $1 and $250")
    if spend != spend.quantize(Decimal("0.01")):
        raise ValueError("Use dollars and cents, max two decimal places")
    return sym, spend


def _request_id(value):
    try:
        identifier = uuid.UUID(str(value))
        if identifier.version != 4:
            return None
        return str(identifier)
    except (ValueError, TypeError, AttributeError):
        return None


def _reserve(db_path, identifier, symbol, amount):
    """SQLite atomic reservation; keep even if outcome unknown (no automatic retry)."""
    with sqlite3.connect(db_path, timeout=15) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS v19_crypto_rebuy_requests (
            request_id TEXT PRIMARY KEY, symbol TEXT NOT NULL,
            amount_usd TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'reserved',
            broker_order_id TEXT
        )""")
        cur = conn.execute(
            "INSERT OR IGNORE INTO v19_crypto_rebuy_requests(request_id, symbol, amount_usd) VALUES (?, ?, ?)",
            (identifier, symbol, str(amount)),
        )
        return cur.rowcount == 1


def _mark(db_path, identifier, state, order_id=None):
    with sqlite3.connect(db_path, timeout=15) as conn:
        conn.execute(
            "UPDATE v19_crypto_rebuy_requests SET state=?, broker_order_id=? WHERE request_id=?",
            (state, order_id, identifier),
        )


def rebuy_order(client, *, symbol, amount, confirmation, allowed_ids,
                request_id=None, db_path=None, enabled=False, allow_live=False, is_paper=None):
    result = {"ok": False, "orderSubmitted": False}
    if not enabled:
        return {**result, "message": "Reports Buy Again is disabled by default"}
    try:
        sym, spend = parse_request(symbol, amount, confirmation)
    except ValueError as exc:
        return {**result, "message": str(exc)}
    if sym not in allowed_ids:
        return {**result, "message": "Coin not found in your closed-trade history"}
    identifier = _request_id(request_id)
    if not identifier or not db_path:
        return {**result, "message": "Missing valid one-time request ID or persistent storage"}
    if not _REBUY_LOCK.acquire(blocking=False):
        return {**result, "message": "Another manual re-buy is being processed"}
    try:
        # Refuse a live account unless a separate explicit live opt-in is set.
        if is_paper is not True and not allow_live:
            return {**result, "message": "Live crypto re-buy is not enabled"}
        # Do not reserve the request until basic broker validation completes.
        asset = client.get_asset(sym.replace("/", ""))
        if "crypto" not in str(getattr(asset, "asset_class", "")).lower() or not getattr(asset, "tradable", False):
            return {**result, "message": "Broker has not verified this coin as tradable"}
        account = client.get_account()
        try:
            available = Decimal(str(getattr(account, "non_marginable_buying_power", "0") or "0"))
        except (InvalidOperation, ValueError, TypeError):
            available = Decimal("-1")
        if not available.is_finite() or available < spend:
            return {**result, "message": "Insufficient verified non-marginable buying power"}
        # Never buy while an existing broker order for this coin remains open.
        # Read failures block the buy rather than assuming no pending orders.
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        open_orders = client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500))
        if any(str(getattr(o, "symbol", "")).replace("/", "").upper() == sym.replace("/", "")
               for o in open_orders):
            return {**result, "message": "An Alpaca order for this coin is still open. Resolve it before rebuying"}
        # Fail closed if order cannot be durably reserved BEFORE calling Alpaca.
        if not _reserve(db_path, identifier, sym, spend):
            return {**result, "message": "This Buy Again request was already processed or attempted. Check broker order history."}
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        # Client-side identifier is stable on a retry and maps to a broker-side
        # client order ID for an additional line of duplicate protection.
        order = client.submit_order(MarketOrderRequest(
            symbol=sym, notional=float(spend), side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
            client_order_id="tb-rebuy-" + identifier,
        ))
        order_id = str(getattr(order, "id", ""))
        _mark(db_path, identifier, "submitted", order_id)
        return {"ok": True, "orderSubmitted": True, "orderId": order_id,
                "message": "Buy request accepted by Alpaca; check fill status"}
    except Exception:
        # If outcome is unknown, the durable reservation must remain. Operator
        # checks broker history; the system NEVER automatically retries.
        return {**result, "message": "Broker outcome uncertain. Check Alpaca order history before attempting another buy"}
    finally:
        _REBUY_LOCK.release()


def enabled():
    return os.getenv("TRADEBOT_REPORTS_CRYPTO_REBUY_ENABLED", "").strip().lower() in ("1", "true", "yes")
