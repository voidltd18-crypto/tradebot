"""Conservative sizing for new stock orders in the original TradeBot."""

from decimal import Decimal, InvalidOperation, ROUND_DOWN

MAX_EQUITY_RISK = Decimal("0.005")
ROUND_TRIP_COST_ALLOWANCE = Decimal("0.003")


def cap_stock_buy_notional(*, requested, equity, cash, buying_power,
                           stop_distance_pct, minimum_order):
    """Limit the order using fresh cash and a modelled loss budget."""
    try:
        requested, equity, cash, buying_power, stop_pct, minimum_order = (
            Decimal(str(value)) for value in (
                requested, equity, cash, buying_power, stop_distance_pct, minimum_order
            )
        )
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("BUY BLOCKED | invalid stock sizing input") from None

    values = (requested, equity, cash, buying_power, stop_pct, minimum_order)
    if any(not value.is_finite() or value <= 0 for value in values) or stop_pct >= 100:
        raise ValueError("BUY BLOCKED | invalid stock sizing input")

    loss_fraction = stop_pct / 100 + ROUND_TRIP_COST_ALLOWANCE
    cash_limit = min(cash, buying_power) / (1 + ROUND_TRIP_COST_ALLOWANCE)
    risk_limit = equity * MAX_EQUITY_RISK / loss_fraction
    amount = min(requested, cash_limit, risk_limit).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )
    if amount < minimum_order:
        raise ValueError("BUY BLOCKED | risk-capped stock order below minimum")
    return float(amount)
