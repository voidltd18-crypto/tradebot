"""Read-only manual crypto rebuy signals. Never submits orders."""
from decimal import Decimal, InvalidOperation

def _number(value):
    try:
        v = Decimal(str(value))
        return v if v.is_finite() and v > 0 else None
    except (TypeError, ValueError, InvalidOperation):
        return None

def assess_manual_rebuy(*, last_filled_sell_price, current_ask, sell_verified,
                        quote_fresh, recovery_confirmed=False,
                        position_open=False, order_pending=False):
    """Fail closed; return WAIT, WATCH or BUY_CANDIDATE, never an order."""
    base = {"status": "WAIT", "readOnly": True, "orderSubmitted": False}
    sold, ask = _number(last_filled_sell_price), _number(current_ask)
    if not sell_verified or not quote_fresh or sold is None or ask is None:
        return {**base, "reason": "Verified sale and fresh broker ask required"}
    if position_open or order_pending:
        reason = ("Existing position and open order" if position_open and order_pending else
                  "Existing position" if position_open else "Open order pending")
        return {**base, "reason": reason, "positionOpen": bool(position_open),
                "orderPending": bool(order_pending)}
    dip = (sold - ask) / sold * Decimal("100")
    info = {**base, "dipPct": str(dip.quantize(Decimal("0.01"))),
            "referenceSalePrice": str(sold), "currentAsk": str(ask)}
    if dip < 3:
        return {**info, "reason": "Waiting for at least 3% pullback from filled sale"}
    if dip < 5:
        return {**info, "status": "WATCH", "reason": "3–5% pullback; monitor for recovery"}
    if not recovery_confirmed:
        return {**info, "status": "WATCH", "reason": "Dip reached; recovery not verified"}
    return {**info, "status": "BUY_CANDIDATE",
            "reason": "5%+ pullback and independently confirmed recovery; manual decision only"}
