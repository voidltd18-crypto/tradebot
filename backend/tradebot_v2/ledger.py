"""Read-only position ownership ledger and reconciliation.

Ledger records are immutable events from an external durable store. This module
does not create, import, or infer ownership from Alpaca positions. Unverified
records fail closed. No order submission functions exist.
"""
from dataclasses import dataclass
from math import isfinite
from datetime import datetime, timezone
from typing import Iterable

@dataclass(frozen=True)
class OwnershipEvent:
    event_id: str
    symbol: str
    broker_order_id: str
    kind: str  # BUY_FILLED or SELL_FILLED
    quantity: float
    recorded_at: datetime

@dataclass(frozen=True)
class OwnershipSnapshot:
    verified: bool
    managed: dict[str, float]
    reason: str


def reconcile(events: Iterable[OwnershipEvent] | None, broker_positions: dict[str, float] | None) -> OwnershipSnapshot:
    """Only exact ledger-to-broker matches can be called verified bot ownership.

    A broker position may contain manually purchased shares, so an exact
    quantity match is necessary but not proof of ownership by itself.
    Records must originate from a separately verified bot order lifecycle.
    """
    if events is None or broker_positions is None:
        return OwnershipSnapshot(False, {}, "Durable ledger or broker state unavailable")
    events = list(events)
    if not events:
        return OwnershipSnapshot(False, {}, "No verified bot-originated fills recorded")
    seen = set()
    totals: dict[str, float] = {}
    for e in sorted(events, key=lambda x: (x.recorded_at, x.event_id)):
        if not e.event_id or not e.broker_order_id or e.event_id in seen:
            return OwnershipSnapshot(False, {}, "Missing or duplicate event/order identity")
        seen.add(e.event_id)
        if e.recorded_at.tzinfo is None or e.recorded_at > datetime.now(timezone.utc):
            return OwnershipSnapshot(False, {}, "Invalid event timestamp")
        if e.kind not in {"BUY_FILLED", "SELL_FILLED"} or not isinstance(e.quantity, (int, float)) or not isfinite(e.quantity) or e.quantity <= 0:
            return OwnershipSnapshot(False, {}, "Invalid fill event")
        symbol = e.symbol.strip().upper()
        if not symbol:
            return OwnershipSnapshot(False, {}, "Missing symbol")
        delta = e.quantity if e.kind == "BUY_FILLED" else -e.quantity
        totals[symbol] = totals.get(symbol, 0.0) + delta
        if totals[symbol] < -1e-8:
            return OwnershipSnapshot(False, {}, "Sale exceeds bot-owned shares")
    active = {symbol: round(qty, 8) for symbol, qty in totals.items() if qty > 1e-8}
    for symbol, qty in active.items():
        broker_qty = broker_positions.get(symbol)
        if broker_qty is None or not isinstance(broker_qty, (int, float)) or not isfinite(broker_qty) or broker_qty < 0 or broker_qty + 1e-8 < qty:
            return OwnershipSnapshot(False, {}, "Broker holdings cannot reconcile with bot ledger")
    return OwnershipSnapshot(True, active, "Verified ledger quantities reconcile with broker holdings")
