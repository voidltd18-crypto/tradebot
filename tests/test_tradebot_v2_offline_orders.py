import pytest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from backend.tradebot_v2.offline_orders import OfflineOrders


def test_idempotent_reservation():
    s = OfflineOrders()
    a = s.reserve("AAPL", "BUY", "1", "request-a")
    assert s.reserve("AAPL", "BUY", "1", "request-a") == a


def test_concurrent_duplicate_blocked():
    s = OfflineOrders()
    def reserve(i):
        try:
            return s.reserve("NVDA", "BUY", 1, str(i))
        except RuntimeError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(24)))
    assert sum(r is not None for r in results) == 1


def test_timeout_and_partial_fill_recovery():
    s = OfflineOrders()
    a = s.reserve("MSFT", "BUY", 2, "r1")
    s.update("r1", "submitted_unknown", 0)
    s.update("r1", "accepted", 0)
    partial = s.update("r1", "partially_filled", "0.5")
    assert partial.filled == Decimal("0.5")
    assert s.update("r1", "partially_filled", "0.5") == partial
    done = s.update("r1", "filled", 2)
    assert done.client_order_id == a.client_order_id
    assert s.reserve("MSFT", "BUY", 1, "r2").status == "reserved"


def test_invalid_transitions_and_fills_blocked():
    s = OfflineOrders()
    s.reserve("META", "SELL", 1, "r1")
    with pytest.raises(ValueError):
        s.update("r1", "filled", "0.5")
    with pytest.raises(ValueError):
        s.update("r1", "accepted", float("nan"))
    with pytest.raises(ValueError):
        s.update("r1", "rejected", 1)


def test_shutdown_blocks_new_orders():
    s = OfflineOrders()
    s.shutdown = True
    with pytest.raises(RuntimeError):
        s.reserve("AAPL", "BUY", 1, "r1")
