"""Single fail-closed offline orchestration gate for TradeBot 2.0.

No broker SDK, no HTTP, no order submission. A GREEN result only authorises
a local simulated reservation, never a live or paper trade.
"""
from dataclasses import dataclass
from datetime import datetime
from math import isfinite

from backend.tradebot_v2.engine import (
    TECH_UNIVERSE, Position, OrderRecord, entry_gate, evaluate_pullback,
)
from backend.tradebot_v2.ledger import reconcile
from backend.tradebot_v2.offline_orders import OfflineOrders


@dataclass(frozen=True)
class SimulationDecision:
    status: str
    reason: str
    simulated_order_id: str | None = None


def simulate_buy(*, symbol: str, closes: list[float],
                 positions: list[Position] | None,
                 orders: list[OrderRecord] | None,
                 now: datetime, market_open: bool,
                 buying_power: float, estimated_cost: float,
                 request_id: str, simulator: OfflineOrders,
                 emergency_shutdown: bool = False) -> SimulationDecision:
    """Gate signal, entire account state and funding before offline reservation."""
    if emergency_shutdown or simulator.shutdown:
        return SimulationDecision("RED", "Emergency shutdown")
    if symbol not in TECH_UNIVERSE:
        return SimulationDecision("RED", "Unapproved symbol")
    if market_open is not True:
        return SimulationDecision("RED", "Market not verified open")
    if not isinstance(buying_power, (int, float)) or not isfinite(buying_power):
        return SimulationDecision("RED", "Buying power unavailable")
    if not isinstance(estimated_cost, (int, float)) or not isfinite(estimated_cost) or estimated_cost <= 0:
        return SimulationDecision("RED", "Estimated cost invalid")
    if buying_power < estimated_cost:
        return SimulationDecision("RED", "Insufficient buying power")
    if not isinstance(closes, list):
        return SimulationDecision("RED", "Price history unavailable")
    gate = entry_gate(symbol, positions, orders, now)
    if gate.status != "AMBER" or not gate.reason.startswith("Entry safeguards passed"):
        return SimulationDecision("RED", gate.reason)
    signal = evaluate_pullback(symbol, closes)
    if signal.status != "GREEN":
        return SimulationDecision("RED", signal.reason)
    try:
        reserved = simulator.reserve(symbol, "BUY", 1, request_id)
    except (ValueError, RuntimeError, TypeError) as exc:
        return SimulationDecision("RED", f"Offline reservation rejected: {exc}")
    return SimulationDecision("GREEN", "Offline simulation only; no broker order",
                              reserved.client_order_id)


def simulate_sell(*, symbol: str, quantity: float, broker_positions: dict,
                  verified_fill_events, request_id: str, simulator: OfflineOrders,
                  emergency_shutdown: bool = False,
                  require_exclusive_ownership: bool = False,
                  position_provenance_verified: bool = False) -> SimulationDecision:
    """Only simulate a sale of reconciled bot-owned shares.

    Ledger event provenance must be independently verified before production use.
    """
    if emergency_shutdown or simulator.shutdown:
        return SimulationDecision("RED", "Emergency shutdown")
    if symbol not in TECH_UNIVERSE:
        return SimulationDecision("RED", "Unapproved symbol")
    if not isinstance(quantity, (int, float)) or not isfinite(quantity) or quantity <= 0:
        return SimulationDecision("RED", "Invalid sale quantity")
    try:
        ownership = reconcile(verified_fill_events, broker_positions)
    except (TypeError, ValueError, AttributeError):
        return SimulationDecision("RED", "Ownership unavailable")
    if not ownership.verified or ownership.managed.get(symbol, 0) < quantity:
        return SimulationDecision("RED", "Sale exceeds verified bot-owned quantity")
    if require_exclusive_ownership and (not position_provenance_verified
                                        or ownership.managed[symbol] != broker_positions[symbol]):
        return SimulationDecision("RED", "Mixed or unreconciled ownership blocks sale")
    try:
        reserved = simulator.reserve(symbol, "SELL", quantity, request_id)
    except (ValueError, RuntimeError, TypeError) as exc:
        return SimulationDecision("RED", f"Offline reservation rejected: {exc}")
    return SimulationDecision("GREEN", "Offline simulation only; no broker order",
                              reserved.client_order_id)
