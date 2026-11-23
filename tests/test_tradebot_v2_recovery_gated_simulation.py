"""Offline buy gate must reject unresolved durable reservations."""
from datetime import datetime, timezone
from decimal import Decimal
from backend.tradebot_v2.durable_reservations import Reservation
from backend.tradebot_v2.offline_orders import OfflineOrders
from backend.tradebot_v2 import recovery_gated_simulation as module


def inputs():
    return dict(
        symbol="AAPL", closes=[100.0] * 10 + [110.0] * 19 + [108.0],
        positions=[], orders=[], now=datetime.now(timezone.utc),
        market_open=True, buying_power=1000, estimated_cost=108,
        request_id="recovery-gated-buy", simulator=OfflineOrders(),
    )


def test_unknown_durable_order_blocks_buy():
    args = inputs()
    outstanding = Reservation("old", "offline-old", "AAPL", "BUY", Decimal(1), "submitted_unknown")
    result = module.simulate_buy_after_recovery(
        database_url="isolated", recovery_reader=lambda _: [outstanding], **args,
    )
    assert result.status == "RED"
    assert args["simulator"]._orders == {}


def test_durable_outage_blocks_buy():
    args = inputs()
    def outage(_):
        raise ConnectionError("down")
    result = module.simulate_buy_after_recovery(
        database_url="isolated", recovery_reader=outage, **args,
    )
    assert result.status == "RED"
    assert args["simulator"]._orders == {}


def test_missing_durable_database_blocks_buy():
    args = inputs()
    result = module.simulate_buy_after_recovery(
        database_url="", recovery_reader=lambda _: [], **args,
    )
    assert result.status == "RED"
    assert args["simulator"]._orders == {}


def test_clear_durable_preflight_allows_only_offline_simulation():
    args = inputs()
    result = module.simulate_buy_after_recovery(
        database_url="isolated", recovery_reader=lambda _: [], **args,
    )
    assert result.status == "GREEN"
    assert result.simulated_order_id.startswith("sim-")
