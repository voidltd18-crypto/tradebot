"""Additional isolated safety regression coverage; no broker access or database writes."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from backend.tradebot_v2.durable_reservations import reserve_offline
from backend.tradebot_v2.engine import Position, OrderRecord, entry_gate
from backend.tradebot_v2.offline_orders import OfflineOrders

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("symbol", [
    "TSLA", "MARA", "BTC", "ETH", "", " ", None, 123,
])
def test_unapproved_symbols_fail_closed(symbol):
    assert entry_gate(symbol, [], [], NOW).status == "RED"


@pytest.mark.parametrize("quantity", [
    0, -1, "-0.01", "NaN", "Infinity", "-Infinity", None, "abc",
])
def test_durable_reservation_invalid_quantities_fail_before_connection(quantity):
    with pytest.raises(ValueError):
        reserve_offline("postgresql://not-connected", "test-key", "MSFT", "BUY", quantity)


@pytest.mark.parametrize("status", [
    "new", "accepted", "pending_new", "partially_filled", "held", "pending_replace",
])
def test_pending_buy_orders_block_entry(status):
    order = OrderRecord("MSFT", "buy", NOW - timedelta(minutes=10), status)
    result = entry_gate("MSFT", [], [order], NOW)
    assert result.status == "RED"


@pytest.mark.parametrize("hours", [0, 1, 12, 23])
def test_sale_cooldown_active_before_24_hours(hours):
    order = OrderRecord("MSFT", "sell", NOW - timedelta(hours=hours), "filled")
    assert entry_gate("MSFT", [], [order], NOW).status == "AMBER"
    assert "cooldown" in entry_gate("MSFT", [], [order], NOW).reason.lower()


@pytest.mark.parametrize("quantity", [1, 0.5, 100, 0.00001])
def test_manual_position_is_not_available_to_buy_again(quantity):
    assert entry_gate("MSFT", [Position("MSFT", quantity)], [], NOW).status == "RED"


@pytest.mark.parametrize("filled", ["-0.01", "NaN", "Infinity", "2"])
def test_simulator_rejects_invalid_fill_without_changing_order(filled):
    sim = OfflineOrders()
    original = sim.reserve("MSFT", "BUY", 1, "test-key")
    with pytest.raises(ValueError):
        sim.update("test-key", "partially_filled", filled)
    assert sim.reserve("MSFT", "BUY", 1, "test-key") == original


@pytest.mark.parametrize("side", ["HOLD", "SHORT", "", None])
def test_durable_reservation_invalid_sides_fail_before_connection(side):
    with pytest.raises(ValueError):
        reserve_offline("postgresql://not-connected", "test-key", "MSFT", side, 1)
