"""Conservative XRP dip/recovery cycle evaluator, no broker order submission.

Entry and exit are independent; never infer that profit is guaranteed.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _positive(value):
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount > 0 else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def assess_xrp_dip_entry(*, ask, ask_at, positions, open_order_symbols,
                         available_cash, spend_usd, threshold="1.29",
                         completed_exit=True, now=None):
    """Read-only XRP entry check for an opt-in future execution loop.

    Requires a recent executable ask at/below the configured limit.
    No pyramiding: an existing XRP position or pending XRP order blocks entry.
    """
    blocked = {"action": "HOLD", "canEnter": False, "readOnly": True}
    now = now or datetime.now(timezone.utc)
    price, available, amount, limit = (_positive(x) for x in
                                       (ask, available_cash, spend_usd, threshold))
    if any(x is None for x in (price, available, amount, limit)):
        return {**blocked, "reason": "missing or invalid price, cash or settings"}
    if ask_at is None or ask_at.tzinfo is None or ask_at.utcoffset() is None:
        return {**blocked, "reason": "quote timestamp not verified"}
    elapsed = (now - ask_at.astimezone(timezone.utc)).total_seconds()
    if elapsed < 0 or elapsed > 30:
        return {**blocked, "reason": "stale or future ask"}
    if not completed_exit:
        return {**blocked, "reason": "previous cycle sell not broker-confirmed"}
    symbols = {str(s).upper().replace("/", "") for s in positions}
    pending = {str(s).upper().replace("/", "") for s in open_order_symbols}
    if "XRPUSD" in symbols:
        return {**blocked, "reason": "XRP already held; no averaging down"}
    if "XRPUSD" in pending:
        return {**blocked, "reason": "XRP order already open"}
    if amount < Decimal("1") or available < amount:
        return {**blocked, "reason": "insufficient verified USD cash or order below $1"}
    if price > limit:
        return {**blocked, "reason": "ask is above dip threshold"}
    return {**blocked, "action": "ENTRY_CANDIDATE", "canEnter": True,
            "symbol": "XRP/USD", "limitPrice": str(limit),
            "spendUsd": str(amount), "reason": "fresh XRP ask at or below threshold; confirmation required"}
