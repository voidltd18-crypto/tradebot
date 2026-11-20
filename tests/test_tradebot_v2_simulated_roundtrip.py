"""Offline-only end-to-end lifecycle tests; never connects to a broker."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.tradebot_v2.engine import OrderRecord, Position, entry_gate
from backend.tradebot_v2.ledger import OwnershipEvent, reconcile
from backend.tradebot_v2.offline_orders import OfflineOrders

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def fill_event(event_id, kind, qty, symbol="AAPL"):
    return OwnershipEvent(event_id, symbol, "verified-simulation-" + event_id,
                          kind, qty, NOW)


def test_manual_positions_consume_both_slots():
    signal = entry_gate("AAPL", [Position("MSFT", 2), Position("NVDA", 3)], [], NOW)
    assert signal.status == "RED"
    assert "Maximum two positions" in signal.reason


def test_manual_shares_never_become_bot_owned():
    assert not reconcile([], {"MSFT": 2, "NVDA": 3}).verified
    assert reconcile([], {"MSFT": 2, "NVDA": 3}).managed == {}


def test_simulated_buy_partial_fill_sell_reconciles_only_bot_shares():
    orders = OfflineOrders()
    buy = orders.reserve("AAPL", "BUY", 2, "buy-1")
    orders.update("buy-1", "accepted", 0)
    orders.update("buy-1", "partially_filled", 1)
    assert orders.update("buy-1", "filled", 2).filled == Decimal(2)
    # Two simulated bot-owned shares plus three manually owned shares.
    owned = reconcile([fill_event("buy-1", "BUY_FILLED", 2)], {"AAPL": 5})
    assert owned.verified and owned.managed == {"AAPL": 2}
    sell = orders.reserve("AAPL", "SELL", 1, "sell-1")
    assert sell.client_order_id != buy.client_order_id
    orders.update("sell-1", "accepted", 0)
    orders.update("sell-1", "filled", 1)
    owned_after = reconcile([
        fill_event("buy-1", "BUY_FILLED", 2),
        fill_event("sell-1", "SELL_FILLED", 1),
    ], {"AAPL": 4})
    assert owned_after.verified and owned_after.managed == {"AAPL": 1}


def test_simulated_sell_cannot_claim_more_than_bot_owned():
    events = [fill_event("buy-1", "BUY_FILLED", 1),
              fill_event("sell-1", "SELL_FILLED", 2)]
    assert not reconcile(events, {"AAPL": 4}).verified


def test_uncertain_simulated_buy_blocks_opposite_side():
    orders = OfflineOrders()
    orders.reserve("AAPL", "BUY", 1, "buy-1")
    orders.update("buy-1", "submitted_unknown", 0)
    with pytest.raises(RuntimeError):
        orders.reserve("AAPL", "SELL", 1, "sell-1")


def test_pending_buy_reserves_remaining_position_slot():
    signal = entry_gate(
        "AAPL", [Position("MSFT", 2)],
        [OrderRecord("NVDA", "buy", NOW, "accepted")], NOW
    )
    assert signal.status == "RED"
    assert "Position slots reserved" in signal.reason
