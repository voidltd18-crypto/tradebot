from datetime import date, timedelta
import pytest
from backend.v20_tech_swing_research import Bar
from backend.v20_tech_swing_portfolio import portfolio_backtest


def history():
    start = date(2024, 1, 1)
    def build(growth):
        return [Bar(start+timedelta(days=i), 100*(1+growth)**i,
                    101*(1+growth)**i, 99*(1+growth)**i,
                    100*(1+growth)**i, 100000) for i in range(280)]
    return {"MSFT": build(.001), "AAPL": build(.002)}


def test_one_position_read_only():
    r = portfolio_backtest(history())
    assert r["readOnly"] and r["ordersSubmitted"] == 0 and r["onePosition"]
    assert r["assumptions"]["maxAllocationPct"] == 25


def test_invalid_symbols_and_allocation():
    with pytest.raises(ValueError):
        portfolio_backtest({"MARA": next(iter(history().values()))})
    with pytest.raises(ValueError):
        portfolio_backtest(history(), allocation=1)
