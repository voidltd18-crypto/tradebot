"""Read-only XRP repeat-cycle eligibility from a broker-confirmed filled sale.

No purchase orders. Never invent a reference price or allow pyramiding.
"""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN


def _positive(value):
    try:
        amount = Decimal(str(value))
        return amount if amount.is_finite() and amount > 0 else None
    except (TypeError, ValueError, InvalidOperation):
        return None


def assess_xrp_dip_entry(
    *, ask, ask_at, positions, open_order_symbols, available_cash, spend_usd,
    last_sale_price=None, last_sale_at=None, last_sale_filled=False,
    pullback_pct="0.5", cooldown_minutes=30, max_sale_age_days=7, now=None,
):
    """Produce an entry signal only, never an order.

    The reference MUST be Alpaca's most recent confirmed XRP filled SELL
    (filled average price and fill time). A static $1.29 trigger is not used.
    """
    hold = {"action": "HOLD", "canEnter": False, "readOnly": True, "symbol": "XRP/USD"}
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        return {**hold, "reason": "current time must be timezone-aware"}
    price, cash, spend, sold_at_price, pullback = (
        _positive(x) for x in (ask, available_cash, spend_usd, last_sale_price, pullback_pct)
    )
    if not all(x is not None for x in (price, cash, spend, sold_at_price, pullback)):
        return {**hold, "reason": "missing ask, verified sale, cash or configured spend"}
    if not (Decimal("0.5") <= pullback <= Decimal("1.0")):
        return {**hold, "reason": "pullback must be between 0.5% and 1%"}
    if not isinstance(cooldown_minutes, int) or not 15 <= cooldown_minutes <= 1440:
        return {**hold, "reason": "cooldown outside allowed range"}
    if not isinstance(max_sale_age_days, int) or not 1 <= max_sale_age_days <= 30:
        return {**hold, "reason": "sale age setting invalid"}
    if not last_sale_filled:
        return {**hold, "reason": "previous XRP sale not broker-confirmed as filled"}
    for name, stamp in (("ask", ask_at), ("sale", last_sale_at)):
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            return {**hold, "reason": f"{name} timestamp not verified"}
    quote_age = (now - ask_at.astimezone(timezone.utc)).total_seconds()
    if not 0 <= quote_age <= 30:
        return {**hold, "reason": "ask stale or future-dated"}
    elapsed = now - last_sale_at.astimezone(timezone.utc)
    if elapsed < timedelta(0) or elapsed > timedelta(days=max_sale_age_days):
        return {**hold, "reason": "reference sale too old or future-dated"}
    if elapsed < timedelta(minutes=cooldown_minutes):
        return {**hold, "reason": "waiting for post-sale cooldown"}
    held = {str(symbol).upper().replace("/", "") for symbol in positions}
    pending = {str(symbol).upper().replace("/", "") for symbol in open_order_symbols}
    if "XRPUSD" in held:
        return {**hold, "reason": "XRP already held; no averaging down"}
    if "XRPUSD" in pending:
        return {**hold, "reason": "XRP broker order already open"}
    if spend < Decimal("1") or spend > cash:
        return {**hold, "reason": "insufficient verified cash or invalid per-cycle spend"}
    # The broker must independently confirm the limit and available cash at submission.
    limit = (sold_at_price * (Decimal("1") - pullback / 100))
    limit = limit.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    if price > limit:
        return {**hold, "reason": "ask has not pulled back enough",
                "targetAskAtMost": str(limit)}
    return {**hold, "action": "ENTRY_CANDIDATE", "canEnter": True,
            "referenceSalePrice": str(sold_at_price),
            "targetAskAtMost": str(limit), "spendUsd": str(spend),
            "pullbackPct": str(pullback), "reason": "confirmed sale followed by qualifying dip; no buy placed"}
