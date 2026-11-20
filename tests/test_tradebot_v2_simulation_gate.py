from datetime import datetime, timezone
import pytest
from backend.tradebot_v2 import simulation_gate as gate
from backend.tradebot_v2.engine import Position, OrderRecord
from backend.tradebot_v2.ledger import OwnershipEvent
from backend.tradebot_v2.offline_orders import OfflineOrders

NOW = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)


def buy(**overrides):
    params = dict(symbol="AAPL", closes=[100.0] * 40,
                  positions=[], orders=[], now=NOW, market_open=True,
                  buying_power=1000, estimated_cost=100,
                  request_id="test-buy", simulator=OfflineOrders())
    params.update(overrides)
    return gate.simulate_buy(**params)


def test_no_pullback_means_no_order():
    assert buy().status == "RED"


def test_green_signal_reserves_only_offline(monkeypatch):
    monkeypatch.setattr(gate, "evaluate_pullback",
                        lambda s, c: type("Signal", (), {"status": "GREEN"})())
    result = buy()
    assert result.status == "GREEN"
    assert result.simulated_order_id.startswith("sim-")


@pytest.mark.parametrize("changes", [
    {"market_open": False},
    {"positions": None},
    {"orders": None},
    {"positions": [Position("MSFT", 1), Position("NVDA", 1)]},
    {"buying_power": 10},
    {"buying_power": float("nan")},
    {"estimated_cost": 0},
    {"emergency_shutdown": True},
    {"symbol": "TSLA"},
])
def test_buy_fail_closed(monkeypatch, changes):
    monkeypatch.setattr(gate, "evaluate_pullback",
                        lambda s, c: type("Signal", (), {"status": "GREEN"})())
    assert buy(**changes).status == "RED"


def test_simulated_sell_rejects_manual_shares():
    result = gate.simulate_sell(
        symbol="MSFT", quantity=1, broker_positions={"MSFT": 10},
        verified_fill_events=[], request_id="sell",
        simulator=OfflineOrders(),
    )
    assert result.status == "RED"


def test_simulated_sell_rejects_excess_bot_quantity():
    events = [OwnershipEvent("fill-1", "AAPL", "verified-order-1",
                             "BUY_FILLED", 1, NOW)]
    result = gate.simulate_sell(
        symbol="AAPL", quantity=2, broker_positions={"AAPL": 10},
        verified_fill_events=events, request_id="sell",
        simulator=OfflineOrders(),
    )
    assert result.status == "RED"


def test_simulated_sell_only_bot_owned_quantity():
    events = [OwnershipEvent("fill-1", "AAPL", "verified-order-1",
                             "BUY_FILLED", 1, NOW)]
    result = gate.simulate_sell(
        symbol="AAPL", quantity=1, broker_positions={"AAPL": 10},
        verified_fill_events=events, request_id="sell",
        simulator=OfflineOrders(),
    )
    assert result.status == "GREEN"
    assert result.simulated_order_id.startswith("sim-")
