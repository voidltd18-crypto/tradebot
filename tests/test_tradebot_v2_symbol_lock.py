"""No opposite-side overlap while an offline reservation is active."""
import pytest
from backend.tradebot_v2.offline_orders import OfflineOrders


@pytest.mark.parametrize("first,second", [
    ("BUY", "SELL"),
    ("SELL", "BUY"),
    ("BUY", "BUY"),
    ("SELL", "SELL"),
])
def test_active_symbol_blocks_other_side_too(first, second):
    orders = OfflineOrders()
    orders.reserve("MSFT", first, 1, "one")
    with pytest.raises(RuntimeError):
        orders.reserve("MSFT", second, 1, "two")


def test_completed_order_releases_symbol_reservation():
    orders = OfflineOrders()
    orders.reserve("MSFT", "BUY", 1, "one")
    orders.update("one", "accepted", 0)
    orders.update("one", "filled", 1)
    assert orders.reserve("MSFT", "SELL", 1, "two").side == "SELL"
