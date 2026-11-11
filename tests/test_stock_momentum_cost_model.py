from datetime import datetime, timedelta, timezone

import pytest

from backend.stock_momentum_cost_model import CostAssumptions, compare_costed_exits


def observations(prices, last_gap=10):
    initial = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)
    second = 0
    out = []
    for i, price in enumerate(prices):
        if i:
            second += last_gap if i == len(prices) - 1 else 10
        out.append({"timestamp": (initial + timedelta(seconds=second)).isoformat(),
                    "price": price})
    return out


PRICES = [100, 100.3, 101, 102, 103, 102.4, 102.2, 101.9]


def test_next_tick_fill_and_costs_not_signal_tick():
    result = compare_costed_exits(100, observations(PRICES))
    candidate, reference = result["candidate"], result["referenceTrailingExit"]
    assert candidate["status"] == "SIMULATED_FILL"
    assert candidate["triggerPrice"] == 102.4
    assert candidate["nextObservedPrice"] == 102.2
    assert reference["triggerPrice"] == 102.2
    assert reference["nextObservedPrice"] == 101.9
    assert candidate["estimatedExitFill"] < candidate["nextObservedPrice"]
    assert result["candidateMinusReferenceNetPnlUsd"] > 0
    assert result["ordersSubmitted"] == 0
    assert result["dataVerifiedAsFmcHistory"] is False


def test_stale_quote_prevents_assumed_fill():
    result = compare_costed_exits(100, observations(PRICES[:7], last_gap=200))
    assert result["candidate"]["status"] == "STALE_NEXT_QUOTE"
    assert result["candidateMinusReferenceNetPnlUsd"] is None


def test_no_quote_after_trigger_is_not_a_fill():
    result = compare_costed_exits(100, observations(PRICES[:6]))
    assert result["candidate"]["status"] == "NO_NEXT_QUOTE"
    assert result["candidate"]["netPnlUsd"] is None


def test_fee_and_spread_can_erase_small_profit():
    result = compare_costed_exits(
        100, observations(PRICES),
        assumptions=CostAssumptions(spread_bps=200, exit_slippage_bps=100,
                                    shares=1, fee_per_side_usd=1),
    )
    assert result["candidate"]["netPnlUsd"] < 0


@pytest.mark.parametrize("cost", [
    {"spread_bps": -1}, {"exit_slippage_bps": float("nan")},
    {"shares": 0}, {"fee_per_side_usd": -1},
    {"max_fill_delay_seconds": 0},
])
def test_invalid_costs_fail_closed(cost):
    with pytest.raises(ValueError):
        CostAssumptions(**cost)


def test_no_signal_is_not_a_simulated_fill():
    result = compare_costed_exits(100, observations([100, 99.9, 99.7, 99.4, 99]))
    assert result["candidate"]["status"] == "NO_SIGNAL"
    assert result["referenceTrailingExit"]["status"] == "NO_SIGNAL"
