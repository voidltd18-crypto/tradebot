"""TradeBot 2.0: isolated, read-only decision engine.

No broker order submission capability is imported or exposed.
All order placement must remain disabled until a separately reviewed execution layer exists.
"""
from dataclasses import dataclass
from math import isfinite
from datetime import datetime, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("America/New_York")
PENDING_ORDER_STATES = frozenset({
    "new", "accepted", "pending_new", "partially_filled", "held",
    "pending_replace", "pending_cancel", "accepted_for_bidding", "done_for_day",
})
TERMINAL_ORDER_STATES = frozenset({"filled", "canceled", "cancelled", "expired", "rejected", "replaced"})
MAX_POSITIONS = 2
COOLDOWN_HOURS = 24
TECH_UNIVERSE = frozenset({"AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META"})


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float


@dataclass(frozen=True)
class OrderRecord:
    symbol: str
    side: str
    created_at: datetime
    status: str
    filled_quantity: float = 0
    last_fill_at: datetime | None = None


@dataclass(frozen=True)
class Signal:
    symbol: str
    status: str
    reason: str


def entry_gate(
    symbol: str,
    positions: Iterable[Position],
    orders: Iterable[OrderRecord],
    now: datetime | None = None,
) -> Signal:
    """Conservative gate: missing/uncertain broker state must block, never permit, buys."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    symbol = symbol.upper().strip() if isinstance(symbol, str) else ""
    if symbol not in TECH_UNIVERSE:
        return Signal(symbol, "RED", "Outside approved tech universe")
    if positions is None or orders is None:
        return Signal(symbol, "RED", "Broker positions or order history unavailable")
    try:
        positions = list(positions)
        orders = list(orders)
        if any(not isinstance(p.quantity, (int, float)) or not isfinite(p.quantity)
               or p.quantity < 0 or not isinstance(p.symbol, str) or not p.symbol.strip()
               for p in positions):
            return Signal(symbol, "RED", "Broker positions cannot be verified")
        if any(not isinstance(o.symbol, str) or not o.symbol.strip()
               or not isinstance(o.side, str) or o.side.strip().lower() not in {"buy", "sell"}
               or not isinstance(o.status, str)
               or o.status.strip().lower() not in PENDING_ORDER_STATES | TERMINAL_ORDER_STATES
               or not isinstance(o.filled_quantity, (int, float))
               or not isfinite(o.filled_quantity) or o.filled_quantity < 0
               or (o.filled_quantity > 0 and o.last_fill_at is None)
               for o in orders):
            return Signal(symbol, "RED", "Broker order history cannot be verified")
        if any(not isinstance(o.created_at, datetime) or o.created_at.tzinfo is None
               or o.created_at > now
               or (o.last_fill_at is not None and (
                   not isinstance(o.last_fill_at, datetime) or o.last_fill_at.tzinfo is None
                   or not o.created_at <= o.last_fill_at <= now)) for o in orders):
            return Signal(symbol, "RED", "Order timestamp cannot be verified")
    except (TypeError, ValueError, AttributeError):
        return Signal(symbol, "RED", "Broker state cannot be verified")
    if any(p.symbol.strip().upper() == symbol and p.quantity != 0 for p in positions):
        return Signal(symbol, "RED", "Already holding this stock")
    if len({p.symbol.strip().upper() for p in positions if p.quantity != 0}) >= MAX_POSITIONS:
        return Signal(symbol, "RED", "Maximum two positions already held")
    pending_buy_symbols = {
        o.symbol.strip().upper() for o in orders
        if o.side.strip().lower() == "buy" and o.status.strip().lower() in PENDING_ORDER_STATES
    }
    held_symbols = {p.symbol.strip().upper() for p in positions if p.quantity != 0}
    if len(held_symbols | pending_buy_symbols) >= MAX_POSITIONS and symbol not in held_symbols:
        return Signal(symbol, "RED", "Position slots reserved by holdings or pending buys")
    for order in orders:
        if order.symbol.strip().upper() != symbol:
            continue
        status = order.status.strip().lower()
        side = order.side.strip().lower()
        if status in PENDING_ORDER_STATES:
            return Signal(symbol, "RED", "Existing pending order")
        if status != "filled" and order.filled_quantity == 0:
            continue
        fill_at = order.last_fill_at or order.created_at
        if side == "buy" and fill_at.astimezone(MARKET_TIMEZONE).date() == now.astimezone(MARKET_TIMEZONE).date():
            return Signal(symbol, "RED", "Already bought today")
        if side == "sell":
            elapsed = (now - fill_at).total_seconds()
            if elapsed < COOLDOWN_HOURS * 3600:
                return Signal(symbol, "AMBER", "Post-sale cooldown active")
    return Signal(symbol, "AMBER", "Entry safeguards passed; price signal not yet verified")


def evaluate_pullback(symbol: str, closes: list[float]) -> Signal:
    """Research-only signal; requires backtesting before any use in trading."""
    symbol = symbol.upper().strip() if isinstance(symbol, str) else ""
    if symbol not in TECH_UNIVERSE:
        return Signal(symbol, "RED", "Outside approved tech universe")
    if len(closes) < 30 or any(not isinstance(p, (int, float)) or not isfinite(p) or p <= 0 for p in closes):
        return Signal(symbol, "AMBER", "Insufficient valid price history")
    recent = closes[-1]
    avg20 = sum(closes[-20:]) / 20
    avg30 = sum(closes[-30:]) / 30
    if recent < avg30 * 0.93:
        return Signal(symbol, "RED", "Sharp decline: trend risk")
    if avg20 > avg30 and avg20 * 0.97 <= recent <= avg20 * 0.995:
        return Signal(symbol, "GREEN", "Pullback candidate; entry gate must also pass")
    return Signal(symbol, "AMBER", "No confirmed pullback setup")
