from datetime import datetime, timedelta, timezone

import pytest

from backend.stock_momentum_replay import replay_stock_exits


def rows(prices, *, gap_after=None):
    now = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
    elapsed = 0
    out = []
    for i, price in enumerate(prices):
        if i and i == gap_after:
            elapsed += 600
        out.append({"timestamp": (now + timedelta(seconds=elapsed)).isoformat(),
                    "price": price})
        elapsed += 10
    return out


def test_spike_gets_tighter_exit_than_baseline():
    result = replay_stock_exits(100, rows([100, 100.3, 101, 102, 103, 102.4, 102.2]))
    assert result["candidateFirstExit"]["price"] == 102.4
    assert result["candidateFirstExit"]["mode"] == "SPIKE"
    assert result["baselineFirstExit"]["price"] == 102.2
    assert result["ordersSubmitted"] == 0
    assert result["enabledForLiveTrading"] is False


def test_steady_rise_is_trend_mode():
    prices = [100, 100.3, 100.6, 100.9, 101.2, 101.5, 101.8, 102.1, 102.4, 101.6]
    result = replay_stock_exits(100, rows(prices))
    assert result["candidateFirstExit"]["mode"] == "TREND"
    assert result["candidateFirstExit"]["price"] == 101.6


def test_stale_gap_resets_acceleration_and_requires_new_samples():
    result = replay_stock_exits(100, rows([100, 101, 102, 103, 104, 103], gap_after=5))
    assert result["events"][4]["mode"] == "SPIKE"
    assert result["events"][5]["mode"] == "TREND"
    assert result["events"][5]["candidateTrigger"] is False


def test_no_profit_exit_for_underwater_position():
    result = replay_stock_exits(100, rows([100, 101, 103, 99, 98, 97]))
    assert result["candidateFirstExit"] is None


def test_no_future_data_lookahead():
    prices = [100, 100.3, 101, 102, 103, 102.4, 102.2]
    full = replay_stock_exits(100, rows(prices))
    prefix = replay_stock_exits(100, rows(prices[:5]))
    assert full["events"][:5] == prefix["events"]
    assert prefix["candidateFirstExit"] is None


@pytest.mark.parametrize("bad_rows", [
    [],
    [{"timestamp": "2026-11-10T14:30:00", "price": 100}],
    [{"timestamp": "2026-11-10T14:30:00Z", "price": 0}],
    [{"timestamp": "2026-11-10T14:30:00Z", "price": float("nan")}],
    [{"timestamp": "2026-11-10T14:30:00Z", "price": 100},
     {"timestamp": "2026-11-10T14:30:00Z", "price": 101}],
])
def test_invalid_data_fails_closed(bad_rows):
    with pytest.raises(ValueError):
        replay_stock_exits(100, bad_rows)


def test_sequential_peak_does_not_use_future_prices():
    result = replay_stock_exits(100, rows([100, 101, 100.5, 102, 104]))
    assert result["events"][2]["peakDrawdownPct"] == pytest.approx(0.495, abs=0.002)
    assert result["events"][4]["peakDrawdownPct"] == 0
