"""Offline-only order lifecycle simulator. Never imports a broker or sends orders."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from threading import RLock
from uuid import uuid4

FINAL = frozenset({"filled", "rejected", "cancelled"})
TRANSITIONS = {
    "reserved": frozenset({"submitted_unknown", "accepted", "rejected", "cancelled"}),
    "submitted_unknown": frozenset({"accepted", "partially_filled", "filled", "rejected", "cancelled"}),
    "accepted": frozenset({"partially_filled", "filled", "rejected", "cancelled"}),
    "partially_filled": frozenset({"partially_filled", "filled", "cancelled"}),
}


@dataclass(frozen=True)
class SimulatedOrder:
    client_order_id: str
    symbol: str
    side: str
    quantity: Decimal
    filled: Decimal
    status: str


class OfflineOrders:
    """Thread-safe in-memory test double, NOT durable or production-ready."""

    def __init__(self):
        self._lock = RLock()
        self._orders = {}
        self._active = set()
        self.shutdown = False

    def reserve(self, symbol, side, quantity, request_id):
        with self._lock:
            if self.shutdown:
                raise RuntimeError("Emergency shutdown")
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("Missing idempotency key")
            if request_id in self._orders:
                return self._orders[request_id]
            symbol = symbol.strip().upper() if isinstance(symbol, str) else ""
            side = side.upper() if isinstance(side, str) else ""
            try:
                qty = Decimal(str(quantity))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("Invalid quantity") from None
            if not qty.is_finite() or qty <= 0 or side not in {"BUY", "SELL"}:
                raise ValueError("Invalid order")
            if (symbol, side) in self._active:
                raise RuntimeError("Duplicate active order")
            order = SimulatedOrder("sim-" + uuid4().hex, symbol, side, qty, Decimal(0), "reserved")
            self._orders[request_id] = order
            self._active.add((symbol, side))
            return order

    def update(self, request_id, status, cumulative_filled):
        with self._lock:
            order = self._orders[request_id]
            try:
                filled = Decimal(str(cumulative_filled))
            except (InvalidOperation, TypeError, ValueError):
                raise ValueError("Invalid fill") from None
            if not filled.is_finite() or not 0 <= filled <= order.quantity or filled < order.filled:
                raise ValueError("Invalid cumulative fill")
            if status == order.status and filled == order.filled:
                return order
            if status not in TRANSITIONS.get(order.status, frozenset()):
                raise ValueError("Invalid lifecycle transition")
            if status == "filled" and filled != order.quantity:
                raise ValueError("Full fill quantity mismatch")
            if status == "rejected" and filled != 0:
                raise ValueError("Rejected order has fills")
            updated = SimulatedOrder(order.client_order_id, order.symbol, order.side,
                                     order.quantity, filled, status)
            self._orders[request_id] = updated
            if status in FINAL:
                self._active.discard((order.symbol, order.side))
            return updated
