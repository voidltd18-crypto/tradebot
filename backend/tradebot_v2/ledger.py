"""Read-only position ownership ledger and reconciliation.

Ledger records are immutable events from an external durable store. This module
does not create, import, or infer ownership from Alpaca positions. Unverified
records fail closed. No order submission functions exist.
"""
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from typing import Iterable

@dataclass(frozen=True)
class OwnershipEvent:
    event_id: str
    symbol: str
    broker_order_id: str
    kind: str  # BUY_FILLED or SELL_FILLED
    quantity: Decimal | float
    recorded_at: datetime

@dataclass(frozen=True)
class OwnershipSnapshot:
    verified: bool
    managed: dict[str, float]
    reason: str


def reconcile(events: Iterable[OwnershipEvent] | None,
              broker_positions: dict[str, Decimal | float] | None) -> OwnershipSnapshot:
    """Reconcile verified ledger fills with quantities held by the broker.

    A broker position may include manual shares, and even an exact quantity
    match does not prove the provenance of the shares currently held.
    Records must originate from a separately verified bot order lifecycle.
    """
    if events is None or broker_positions is None:
        return OwnershipSnapshot(False, {}, "Durable ledger or broker state unavailable")
    events = list(events)
    if not events:
        return OwnershipSnapshot(False, {}, "No verified bot-originated fills recorded")
    seen = set()
    totals: dict[str, Decimal] = {}
    for e in sorted(events, key=lambda x: (x.recorded_at, x.event_id)):
        if not e.event_id or not e.broker_order_id or e.event_id in seen:
            return OwnershipSnapshot(False, {}, "Missing or duplicate event/order identity")
        seen.add(e.event_id)
        if e.recorded_at.tzinfo is None or e.recorded_at > datetime.now(timezone.utc):
            return OwnershipSnapshot(False, {}, "Invalid event timestamp")
        quantity = _decimal_quantity(e.quantity)
        if e.kind not in {"BUY_FILLED", "SELL_FILLED"} or quantity is None or quantity <= 0:
            return OwnershipSnapshot(False, {}, "Invalid fill event")
        symbol = e.symbol.strip().upper()
        if not symbol:
            return OwnershipSnapshot(False, {}, "Missing symbol")
        delta = quantity if e.kind == "BUY_FILLED" else -quantity
        totals[symbol] = totals.get(symbol, Decimal(0)) + delta
        if totals[symbol] < 0:
            return OwnershipSnapshot(False, {}, "Sale exceeds bot-owned shares")
    active = {symbol: qty for symbol, qty in totals.items() if qty > 0}
    for symbol, qty in active.items():
        broker_qty = _decimal_quantity(broker_positions.get(symbol))
        if broker_qty is None or broker_qty < qty:
            return OwnershipSnapshot(False, {}, "Broker holdings cannot reconcile with bot ledger")
    return OwnershipSnapshot(True, {symbol: float(qty) for symbol, qty in active.items()},
                             "Verified ledger quantities reconcile with broker holdings")


def _decimal_quantity(value):
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float)):
        return None
    quantity = Decimal(str(value))
    return quantity if quantity.is_finite() else None
