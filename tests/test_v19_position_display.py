"""Regression tests for broker-consistent displayed P/L (read-only)."""
from types import SimpleNamespace
from backend.v19_position_display import broker_display_values


def test_alpaca_values_win_over_stale_iex_quote():
    position = SimpleNamespace(
        qty="162.416590729", avg_entry_price="5.485",
        current_price="5.515", market_value="895.71",
        cost_basis="890.85", unrealized_pl="4.86", unrealized_plpc="0.0054",
    )
    price, pnl, pct = broker_display_values(position, fallback_quote=5.38)
    assert price == 5.515
    assert pnl == 4.86
    assert pct == 0.54


def test_broker_fallback_from_market_value_and_cost_basis():
    position = SimpleNamespace(
        qty="2", avg_entry_price="10", current_price=None,
        market_value="22", cost_basis="20",
        unrealized_pl=None, unrealized_plpc=None,
    )
    price, pnl, pct = broker_display_values(position, fallback_quote=9)
    assert price == 11
    assert pnl == 2
    assert round(pct, 8) == 10


def test_fallback_quote_if_broker_mark_unavailable():
    position = SimpleNamespace(
        qty="2", avg_entry_price="10", current_price=None,
        market_value=None, cost_basis=None,
        unrealized_pl=None, unrealized_plpc=None,
    )
    price, pnl, pct = broker_display_values(position, fallback_quote=9)
    assert (price, pnl, pct) == (9, -2, -10)


def test_nonfinite_quote_does_not_poison_display():
    position = SimpleNamespace(
        qty="1", avg_entry_price="5", current_price=float("nan"),
        market_value="6", cost_basis="5",
        unrealized_pl="1", unrealized_plpc="0.2",
    )
    assert broker_display_values(position, 999) == (6, 1, 20)
