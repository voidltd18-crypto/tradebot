"""Regression: distinguish experimental 2% entry-arm from repository's
published 1.2% TRAIL_START_PCT default. This does not verify live Render values.
"""
from datetime import datetime, timedelta, timezone

import pytest

from backend.stock_momentum_cost_model import compare_costed_exits
from backend.stock_momentum_replay import replay_stock_exits


def observations(prices):
    start = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
    return [{"timestamp": (start + timedelta(minutes=i)).isoformat(),
             "price": price} for i, price in enumerate(prices)]


def test_configured_baseline_arms_before_experimental_spike():
    prices = [100, 100.4, 100.8, 101.2, 101.6, 100.8, 100.7]
    rows = observations(prices)
    original = replay_stock_exits(100, rows)
    assert original["baselineFirstExit"] is None
    configured = replay_stock_exits(100, rows, reference_activation_pct=1.2)
    assert configured["referenceActivationPct"] == 1.2
    assert configured["candidateFirstExit"] is None
    assert configured["baselineFirstExit"]["price"] == 100.8
    costs = compare_costed_exits(100, rows, reference_activation_pct=1.2)
    assert costs["candidate"]["status"] == "NO_SIGNAL"
    assert costs["referenceTrailingExit"]["status"] == "SIMULATED_FILL"


@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf")])
def test_invalid_reference_activation_refused(invalid):
    with pytest.raises(ValueError):
        replay_stock_exits(100, observations([100, 101]), reference_activation_pct=invalid)
