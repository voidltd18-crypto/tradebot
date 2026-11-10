"""Fail-closed readiness checks for a FUTURE opt-in crypto profit-only executor.

Never places orders. A gross-positive notification is not a sell instruction.
"""
from decimal import Decimal, InvalidOperation


def _number(value):
    try:
        v = Decimal(str(value))
        if not v.is_finite() or v <= 0:
            return None
        return v
    except (InvalidOperation, TypeError, ValueError):
        return None


def assess_profit_exit(*, entry, quantity, bid, verified_peak, fee_rate,
                       trail_activation_pct="1", trail_giveback_pct="1",
                       estimated_slippage_pct="0.25", managed=False,
                       pending_sell=False, price_age_seconds=None):
    """Read-only estimated net profitability and verified trailing trigger."""
    result = {"status": "blocked", "action": "NO_ACTION", "readOnly": True,
              "netProfitPositive": False, "readyForExecution": False}
    if not managed:
        return {**result, "reason": "position has not explicitly opted into management"}
    if pending_sell:
        return {**result, "reason": "existing or unresolved sell order"}
    if price_age_seconds is None or not isinstance(price_age_seconds, (int, float)) or price_age_seconds < 0 or price_age_seconds > 30:
        return {**result, "reason": "bid freshness unverified or stale"}
    vals = [_number(x) for x in (entry, quantity, bid, verified_peak)]
    if any(v is None for v in vals):
        return {**result, "reason": "entry, quantity, bid or verified peak missing"}
    cost, qty, sell_bid, peak = vals
    if peak < sell_bid:
        return {**result, "reason": "verified peak below current bid"}
    try:
        fee = Decimal(str(fee_rate))
        slip = Decimal(str(estimated_slippage_pct)) / 100
        activate = Decimal(str(trail_activation_pct)) / 100
        giveback = Decimal(str(trail_giveback_pct)) / 100
    except (InvalidOperation, ValueError, TypeError):
        return {**result, "reason": "invalid fee or trailing configuration"}
    if not all(v.is_finite() for v in (fee, slip, activate, giveback)) or not (0 <= fee < 1 and 0 <= slip < 1 and 0 < activate < 1 and 0 < giveback < 1):
        return {**result, "reason": "fee or trailing configuration out of range"}
    conservative_exit = sell_bid * (1 - slip)
    net_proceeds = qty * conservative_exit * (1 - fee)
    entry_cost = qty * cost
    net_profit = net_proceeds - entry_cost
    details = {**result, "estimatedNetProfitUsd": str(net_profit),
               "netProfitPositive": bool(net_profit > 0)}
    if net_profit <= 0:
        return {**details, "reason": "no positive estimated profit after sell costs and slippage"}
    if peak < cost * (1 + activate):
        return {**details, "reason": "trailing profit not activated"}
    if sell_bid > peak * (1 - giveback):
        return {**details, "reason": "verified trailing floor has not been crossed"}
    return {**details, "status": "candidate", "reason": "candidate only; execution disabled; broker revalidation required"}
