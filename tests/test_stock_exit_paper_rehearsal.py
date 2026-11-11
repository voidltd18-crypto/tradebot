"""Safety tests for hypothetical stock sells; no account access."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.stock_exit_paper_rehearsal import (
    reconcile_order_updates, rehearse_exit_gate,
)

T0 = datetime(2026, 11, 10, 14, 30, tzinfo=timezone.utc)


def stamp(seconds):
    return (T0 + timedelta(seconds=seconds)).isoformat()


def gate(**overrides):
    payload = dict(
        symbol="FMC", position_qty=100, candidate_exit=True,
        quote_timestamp=stamp(0), now=stamp(2),
        market_open=True, account_sell_allowed=True,
        existing_orders=[],
    )
    payload.update(overrides)
    return rehearse_exit_gate(**payload)


def test_fresh_exit_candidate_is_only_a_diagnostic():
    result = gate()
    assert result["wouldPassPreflight"] is True
    assert result["ordersSubmitted"] == 0
    assert result["brokerOrderCreated"] is False
    assert result["requiresFreshBrokerReconciliation"] is True


@pytest.mark.parametrize("change,reason", [
    ({"candidate_exit": False}, "NO_EXIT_SIGNAL"),
    ({"position_qty": 0}, "NO_POSITION"),
    ({"market_open": False}, "MARKET_CLOSED"),
    ({"account_sell_allowed": False}, "ACCOUNT_RESTRICTION"),
    ({"now": stamp(60)}, "STALE_PRICE"),
    ({"existing_orders": [{"id": "sell1", "symbol": "FMC",
                            "side": "sell", "status": "partially_filled"}]},
     "EXISTING_WORKING_SELL"),
    ({"existing_orders": [{"id": "sell2", "symbol": "FMC",
                            "side": "sell", "status": "unknown"}]},
     "UNKNOWN_ORDER_STATUS"),
])
def test_safety_blocks_sell_preflight(change, reason):
    result = gate(**change)
    assert not result["wouldPassPreflight"]
    assert reason in result["reasons"]
    assert result["ordersSubmitted"] == 0


def test_buy_order_does_not_look_like_working_sell():
    result = gate(existing_orders=[{"id": "buy1", "symbol": "FMC",
                                    "side": "buy", "status": "accepted"}])
    assert result["wouldPassPreflight"] is True


def test_partial_and_full_fill_reconciliation():
    results = reconcile_order_updates([
        {"id": "o1", "timestamp": stamp(0), "status": "accepted", "qty": 10, "filled_qty": 0},
        {"id": "o1", "timestamp": stamp(1), "status": "partially_filled", "qty": 10, "filled_qty": 3},
        {"id": "o1", "timestamp": stamp(2), "status": "filled", "qty": 10, "filled_qty": 10},
    ])
    assert results["remainingQty"] == 0
    assert results["terminal"]
    assert results["ordersSubmitted"] == 0


def test_rejected_order_is_terminal_but_requires_reconciliation():
    result = reconcile_order_updates([
        {"id": "o2", "timestamp": stamp(0), "status": "accepted", "qty": 10, "filled_qty": 0},
        {"id": "o2", "timestamp": stamp(1), "status": "rejected", "qty": 10, "filled_qty": 0},
    ])
    assert result["terminal"]
    assert result["needsPositionRefresh"]


@pytest.mark.parametrize("updates", [
    [{"id": "o", "timestamp": stamp(0), "status": "filled", "qty": 10, "filled_qty": 5}],
    [{"id": "o", "timestamp": stamp(0), "status": "accepted", "qty": 10, "filled_qty": 5},
     {"id": "o", "timestamp": stamp(1), "status": "accepted", "qty": 10, "filled_qty": 4}],
    [{"id": "o", "timestamp": stamp(0), "status": "rejected", "qty": 10, "filled_qty": 0},
     {"id": "o", "timestamp": stamp(1), "status": "accepted", "qty": 10, "filled_qty": 0}],
    [{"id": "o", "timestamp": stamp(0), "status": "accepted", "qty": 10, "filled_qty": 11}],
    [{"id": "o", "timestamp": stamp(0), "status": "accepted", "qty": 10, "filled_qty": 0},
     {"id": "different", "timestamp": stamp(1), "status": "filled", "qty": 10, "filled_qty": 10}],
])
def test_inconsistent_broker_updates_fail_closed(updates):
    with pytest.raises(ValueError):
        reconcile_order_updates(updates)


def test_future_quote_rejected():
    with pytest.raises(ValueError, match="future"):
        gate(quote_timestamp=stamp(10))


def test_invalid_position_qty_rejected():
    with pytest.raises(ValueError):
        gate(position_qty=float("nan"))
