"""Read-only Alpaca crypto exit diagnostics. No order submission.

Explicit opt-in is required in a separate execution component before any
diagnostic recommendation may ever become a live order.
"""
from decimal import Decimal, InvalidOperation


def _positive(value, name):
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"invalid {name}")
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"invalid {name}")
    return amount


def crypto_exit_diagnostic(
    symbol, quantity, entry_price, current_price, highest_price,
    *, stop_loss_pct="4", trail_start_pct="1", trail_giveback_pct="1",
    manage_external=False, externally_purchased=True,
):
    """Produce a conservative observation only, never an executable instruction.

    All percent inputs express positive percentage magnitudes, e.g. 4 = 4%.
    An externally purchased position is explicitly NOT managed by default.
    """
    name = str(symbol or "").strip().upper()
    if not name or not (name.endswith("USD") or name.endswith("USDT")):
        return {"symbol": name, "status": "unsupported", "action": "NO_ACTION",
                "reason": "not a supported USD/USDT crypto symbol"}
    try:
        qty = _positive(quantity, "quantity")
        entry = _positive(entry_price, "entry")
        price = _positive(current_price, "current price")
        peak = _positive(highest_price, "peak price")
        stop = _positive(stop_loss_pct, "stop loss percent")
        start = _positive(trail_start_pct, "trail start percent")
        giveback = _positive(trail_giveback_pct, "trail giveback percent")
        if any(x >= 100 for x in (stop, start, giveback)):
            raise ValueError("risk percentages must be less than 100")
        if peak < price:
            raise ValueError("peak cannot be below current price")
    except ValueError as exc:
        return {"symbol": name, "status": "unverified", "action": "NO_ACTION",
                "reason": str(exc)}

    entry_stop = entry * (1 - stop / 100)
    activation = entry * (1 + start / 100)
    armed = peak >= activation
    trail_floor = peak * (1 - giveback / 100) if armed else None
    possible_stop = price <= entry_stop
    possible_trail = bool(armed and price <= trail_floor)
    observed = ("STOP_LOSS_CONDITION" if possible_stop else
                "TRAIL_CONDITION" if possible_trail else "HOLD_CONDITION")
    eligible = bool(manage_external or not externally_purchased)
    return {
        "symbol": name, "status": "observed", "action": "NO_ACTION",
        "mode": "DIAGNOSTIC_ONLY", "eligibleForFutureOptIn": eligible,
        "externalPosition": bool(externally_purchased),
        "quantity": str(qty), "entry": str(entry), "current": str(price),
        "peak": str(peak), "stopPrice": str(entry_stop),
        "trailStartPrice": str(activation),
        "trailArmed": armed,
        "trailFloor": str(trail_floor) if trail_floor is not None else None,
        "condition": observed,
        "reason": "no automatic order submission; diagnostic only",
        "sellOrderSubmitted": False,
    }
