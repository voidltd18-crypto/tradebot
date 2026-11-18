"""Pure offline tests: no Alpaca client and no live order paths."""
from datetime import date, timedelta
import pytest
from backend.v20_tech_swing_research import Bar, backtest, signal, validate


def series(n=270, growth=0.001):
    start = date(2024, 1, 1)
    return [Bar(start + timedelta(days=i), 100 * (1 + growth)**i,
                101 * (1 + growth)**i, 99 * (1 + growth)**i,
                100 * (1 + growth)**i, 100000) for i in range(n)]


def test_no_orders_and_bounded_allocation():
    result = backtest("MSFT", series())
    assert result["readOnly"] is True and result["ordersSubmitted"] == 0
    assert result["assumptions"]["maxAllocationPct"] == 25


def test_no_future_data_in_signal():
    bars = series()
    assert signal(bars, 205) == signal(bars[:206], 205)


def test_rejects_unknown_and_bad_data():
    with pytest.raises(ValueError):
        backtest("MARA", series())
    with pytest.raises(ValueError):
        validate(series(20))
    with pytest.raises(ValueError):
        validate(series() + [series()[-1]])


def test_flat_market_no_forced_buy():
    result = backtest("MSFT", series(growth=0))
    assert result["closedTrades"] == 0
    assert result["finalEquity"] == 10000


def test_gapped_stop_worse_than_stop_price():
    bars = series(260)
    # Entry follows signal at prior close; force a large gap after first entry.
    bars[202] = Bar(bars[202].day, 60, 61, 59, 60, 100000)
    result = backtest("MSFT", bars)
    assert result["ordersSubmitted"] == 0
    assert all(t["reason"] in ("STOP", "TARGET", "TIME", "TREND") for t in result["trades"])
