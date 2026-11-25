from datetime import date, timedelta
import pytest
from backend.v20_tech_swing_research import Bar
from backend.v20_tech_swing_trend_hold import trend_hold


def bars(growth=0.001):
    return [Bar(date(2024, 1, 1) + timedelta(days=i), 100*(1+growth)**i,
                101*(1+growth)**i, 99*(1+growth)**i, 100*(1+growth)**i, 100000)
            for i in range(350)]


def test_read_only_and_bounded():
    r = trend_hold("MSFT", bars())
    assert r["readOnly"] and r["ordersSubmitted"] == 0
    assert r["assumptions"]["maxAllocationPct"] <= 25


def test_flat_prices_no_forced_trade():
    r = trend_hold("MSFT", bars(0))
    assert r["closedTrades"] == 0
    assert r["totalReturnPct"] == 0


def test_invalid_risk_and_symbol_fail_closed():
    with pytest.raises(ValueError):
        trend_hold("MARA", bars())
    with pytest.raises(ValueError):
        trend_hold("MSFT", bars(), allocation=1)
