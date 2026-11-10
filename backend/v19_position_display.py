"""Broker-authoritative position numbers for display only.

Stock execution quotes, peaks and risk profiles are intentionally unaffected.
"""
import math


def _finite(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError, OverflowError):
        return None


def broker_display_values(position, fallback_quote):
    """Use internally consistent Alpaca valuation, not a separate SIP/IEX quote.

    Alpaca's market_value and unrealized_pl share the same mark. Prefer the
    broker's current_price and P/L; if absent, derive from market_value/cost.
    No broker calls or trading actions.
    """
    qty = _finite(getattr(position, "qty", None))
    entry = _finite(getattr(position, "avg_entry_price", None))
    market_value = _finite(getattr(position, "market_value", None))
    cost_basis = _finite(getattr(position, "cost_basis", None))
    broker_price = _finite(getattr(position, "current_price", None))
    broker_pnl = _finite(getattr(position, "unrealized_pl", None))
    broker_pct = _finite(getattr(position, "unrealized_plpc", None))
    fallback = _finite(fallback_quote)
    if broker_price is not None and broker_price > 0:
        price = broker_price
    elif qty and qty > 0 and market_value is not None:
        price = market_value / qty
    else:
        price = fallback if fallback is not None and fallback > 0 else 0.0

    if broker_pnl is not None:
        pnl = broker_pnl
    elif market_value is not None and cost_basis is not None:
        pnl = market_value - cost_basis
    elif qty is not None and entry is not None:
        pnl = (price - entry) * qty
    else:
        pnl = 0.0

    if broker_pct is not None:
        pnl_pct = broker_pct * 100.0
    elif cost_basis is not None and cost_basis > 0 and market_value is not None:
        pnl_pct = (market_value / cost_basis - 1) * 100.0
    elif entry is not None and entry > 0:
        pnl_pct = (price / entry - 1) * 100.0
    else:
        pnl_pct = 0.0
    return price, pnl, pnl_pct
