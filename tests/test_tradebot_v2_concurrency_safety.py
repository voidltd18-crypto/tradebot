"""Concurrency and restart-boundary safety tests; offline and no database writes."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from backend.tradebot_v2.offline_orders import OfflineOrders
from backend.tradebot_v2.durable_reservations import recover_active_offline


def test_parallel_identical_requests_are_idempotent():
    simulator = OfflineOrders()
    barrier = Barrier(12)

    def request(_):
        barrier.wait(timeout=10)
        return simulator.reserve("MSFT", "BUY", 1, "same-key")

    with ThreadPoolExecutor(max_workers=12) as pool:
        orders = list(pool.map(request, range(12)))
    assert len({o.client_order_id for o in orders}) == 1


def test_parallel_distinct_requests_only_one_wins():
    simulator = OfflineOrders()
    barrier = Barrier(12)

    def request(n):
        barrier.wait(timeout=10)
        try:
            return simulator.reserve("NVDA", "BUY", 1, "key-" + str(n))
        except RuntimeError:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        orders = list(pool.map(request, range(12)))
    assert sum(o is not None for o in orders) == 1


@pytest.mark.parametrize("side", ["BUY", "SELL"])
def test_same_side_duplicate_active_order_blocked(side):
    simulator = OfflineOrders()
    simulator.reserve("AAPL", side, 1, "first")
    with pytest.raises(RuntimeError):
        simulator.reserve("AAPL", side, 1, "second")


@pytest.mark.parametrize("state", ["reserved", "submitted_unknown", "accepted", "partially_filled"])
def test_uncertain_or_active_order_blocks_duplicate(state):
    simulator = OfflineOrders()
    simulator.reserve("META", "BUY", 2, "first")
    if state != "reserved":
        simulator.update("first", state, 1 if state == "partially_filled" else 0)
    with pytest.raises(RuntimeError):
        simulator.reserve("META", "BUY", 2, "second")


def test_restart_reader_rejects_missing_database_connection():
    with pytest.raises(ValueError):
        recover_active_offline("")
