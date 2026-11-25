"""Display-only stock exit levels for positions whose provenance is unverified."""

from math import isfinite

from backend.stock_buy_risk import ROUND_TRIP_COST_ALLOWANCE


def stock_sell_preview(*, quantity, entry, mark, stop, emergency_stop,
                       trail_active, trail_floor, owned_quantity=None):
    result = {
        "action": "HOLD",
        "reason": ("Bot shares verified. Execution is disabled." if owned_quantity is not None
                   else "Bot ownership unverified. Selling is blocked."),
        "verifiedBotQuantity": str(owned_quantity) if owned_quantity is not None else None,
        "thresholdSignal": None,
        "estimatedNetPnl": None,
        "costAllowancePct": float(ROUND_TRIP_COST_ALLOWANCE * 100),
    }
    if not all(isfinite(value) and value > 0 for value in (quantity, entry, mark)):
        return result

    stop_levels = [level for level in (stop, emergency_stop) if isfinite(level) and level > 0]
    if any(mark <= level for level in stop_levels):
        result["thresholdSignal"] = "PROTECTIVE EXIT"
    elif trail_active and isfinite(trail_floor) and trail_floor > 0 and mark <= trail_floor:
        result["thresholdSignal"] = "TRAILING EXIT"

    proceeds, basis = quantity * mark, quantity * entry
    estimate = proceeds - basis - basis * float(ROUND_TRIP_COST_ALLOWANCE)
    if isfinite(estimate):
        result["estimatedNetPnl"] = round(estimate, 2)
    return result
