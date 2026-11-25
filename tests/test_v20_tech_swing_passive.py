from datetime import date, timedelta
import pytest
from backend.v20_tech_swing_research import Bar
from backend.v20_tech_swing_passive import passive_basket


def test_flat_basket_has_costs_and_no_orders():
    bars = [Bar(date(2024, 1, 1)+timedelta(days=i), 100, 101, 99, 100, 10000)
            for i in range(240)]
    r = passive_basket({"MSFT": bars, "AAPL": bars})
    assert r["readOnly"] and r["ordersSubmitted"] == 0
    assert r["returnPct"] < 0
    assert r["maxDrawdownPct"] <= 0


def test_invalid_allocation():
    bars = [Bar(date(2024, 1, 1)+timedelta(days=i), 100, 101, 99, 100, 10000)
            for i in range(240)]
    with pytest.raises(ValueError):
        passive_basket({"MSFT": bars}, allocation=2)
