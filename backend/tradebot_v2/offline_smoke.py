"""Deterministic, offline-only TradeBot 2.0 end-to-end smoke scenario.

No network, Alpaca client, credentials, broker submission or database writes.
The BUY/SELL sequence below is synthetic and must never be treated as proof
of actual broker ownership or live-trading readiness.
"""
import json
from datetime import datetime, timezone

from backend.tradebot_v2.engine import Position
from backend.tradebot_v2.ledger import OwnershipEvent
from backend.tradebot_v2.offline_orders import OfflineOrders
from backend.tradebot_v2.simulation_gate import simulate_buy, simulate_sell


def run_smoke():
    now = datetime.now(timezone.utc)
    simulator = OfflineOrders()
    # Synthetic pullback: 20-bar average above 30-bar average; last close
    # is 1-3% below the 20-bar average, without a >7% trend breakdown.
    closes = [100.0] * 10 + [110.0] * 19 + [108.0]
    # One manually owned MSFT position leaves one account-wide slot.
    buy = simulate_buy(
        symbol="AAPL", closes=closes, positions=[Position("MSFT", 3)],
        orders=[], now=now, market_open=True, buying_power=1000,
        estimated_cost=108, request_id="smoke-buy", simulator=simulator,
    )
    if buy.status != "GREEN":
        raise AssertionError("Synthetic eligible buy was blocked: " + buy.reason)
    duplicate = simulate_buy(
        symbol="AAPL", closes=closes, positions=[Position("MSFT", 3)],
        orders=[], now=now, market_open=True, buying_power=1000,
        estimated_cost=108, request_id="smoke-duplicate", simulator=simulator,
    )
    if duplicate.status != "RED":
        raise AssertionError("Duplicate symbol order was not blocked")
    simulator.update("smoke-buy", "accepted", 0)
    simulator.update("smoke-buy", "filled", 1)
    # No bot-originated fill for MSFT: the manual holding cannot be sold.
    manual_sell = simulate_sell(
        symbol="MSFT", quantity=1, broker_positions={"MSFT": 3, "AAPL": 1},
        verified_fill_events=[], request_id="manual-sell", simulator=simulator,
    )
    if manual_sell.status != "RED":
        raise AssertionError("Manual holding was eligible for sale")
    # A synthetic, NOT broker-verified fill used exclusively for this smoke test.
    synthetic_events = [OwnershipEvent(
        "synthetic-fill", "AAPL", "synthetic-order", "BUY_FILLED", 1, now,
    )]
    sell = simulate_sell(
        symbol="AAPL", quantity=1, broker_positions={"MSFT": 3, "AAPL": 1},
        verified_fill_events=synthetic_events, request_id="smoke-sell",
        simulator=simulator,
    )
    if sell.status != "GREEN":
        raise AssertionError("Synthetic bot-owned sale was blocked: " + sell.reason)
    simulator.update("smoke-sell", "accepted", 0)
    simulator.update("smoke-sell", "filled", 1)
    simulator.shutdown = True
    blocked = simulate_buy(
        symbol="NVDA", closes=closes, positions=[Position("MSFT", 3)],
        orders=[], now=now, market_open=True, buying_power=1000,
        estimated_cost=108, request_id="after-shutdown", simulator=simulator,
    )
    if blocked.status != "RED":
        raise AssertionError("Emergency shutdown did not block new orders")
    return {
        "result": "PASS", "execution_enabled": False, "broker_orders": 0,
        "synthetic_buy": buy.status, "duplicate_order": duplicate.status,
        "manual_share_sale": manual_sell.status, "synthetic_sell": sell.status,
        "shutdown_buy": blocked.status,
        "limitations": "In-memory simulation, synthetic fills; no durable restart, "
                       "real broker provenance or live execution verified",
    }


if __name__ == "__main__":
    print(json.dumps(run_smoke(), sort_keys=True))
