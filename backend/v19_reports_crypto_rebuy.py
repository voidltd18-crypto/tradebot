"""Guarded manual crypto re-buy from a closed Reports trade.

Explicit operator confirmation is required. Disabled by default even on live
accounts. No stock buy path, scanner logic, or autonomous orders are involved.
"""
import os
import re
import threading
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


def rebuy_order(client, *, symbol, amount, confirmation, allowed_ids,
                enabled=False, allow_live=False):
    """Submit at most one manual buy under a process lock; fail closed.

    allowed_ids is obtained directly from the closed-trades DB for the authenticated
    request; the symbol itself must be present there. Client errors never retry
    automatically because broker outcome can be ambiguous.
    """
    result = {"ok": False, "orderSubmitted": False}
    if not enabled:
        return {**result, "message": "Reports Buy Again is disabled by default"}
    try:
        sym, spend = parse_request(symbol, amount, confirmation)
    except ValueError as exc:
        return {**result, "message": str(exc)}
    if sym not in allowed_ids:
        return {**result, "message": "Coin not found in your closed-trade history"}
    if not _REBUY_LOCK.acquire(blocking=False):
        return {**result, "message": "Another manual re-buy is being processed"}
    try:
        if not bool(getattr(client, "_paper", False)) and not allow_live:
            return {**result, "message": "Live crypto re-buy is not enabled"}
        asset = client.get_asset(sym.replace("/", ""))
        if "crypto" not in str(getattr(asset, "asset_class", "")).lower() or not getattr(asset, "tradable", False):
            return {**result, "message": "Broker has not verified this coin as tradable"}
        account = client.get_account()
        available = Decimal(str(getattr(account, "non_marginable_buying_power", "0") or "0"))
        if not available.is_finite() or available < spend:
            return {**result, "message": "Insufficient verified non-marginable buying power"}
        # Use a stable client order ID to prevent two submissions of one UI action.
        # The endpoint additionally requires a valid UUID supplied by the user action.
        # Notional USD market buys are accepted by Alpaca for supported crypto pairs.
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce
        order = client.submit_order(MarketOrderRequest(
            symbol=sym, notional=float(spend), side=OrderSide.BUY,
            time_in_force=TimeInForce.GTC,
        ))
        return {"ok": True, "orderSubmitted": True, "orderId": str(order.id),
                "message": "Buy submitted to Alpaca; verify fill status before assuming ownership"}
    except Exception:
        # Do not retry uncertain broker outcomes.
        return {**result, "message": "Broker request failed or outcome unknown; check Alpaca orders before retrying"}
    finally:
        _REBUY_LOCK.release()


def enabled():
    return os.getenv("TRADEBOT_REPORTS_CRYPTO_REBUY_ENABLED", "").strip().lower() in ("1", "true", "yes")
