"""Durable, offline-only reservation gate for the isolated TradeBot v2 database.

No broker imports, order submission, or ledger writes. Unknown outcomes fail closed.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from backend.tradebot_v2.engine import COOLDOWN_HOURS, MARKET_TIMEZONE, TECH_UNIVERSE
from backend.tradebot_v2.offline_orders import TRANSITIONS

QUANTITY_INCREMENT = Decimal("0.00000001")
MAX_QUANTITY = Decimal("10000000000000000")
ACTIVE = frozenset({"reserved", "submitted_unknown", "accepted", "partially_filled"})


@dataclass(frozen=True)
class Reservation:
    request_id: str
    client_order_id: str
    symbol: str
    side: str
    quantity: Decimal
    status: str
    cumulative_filled: Decimal = Decimal(0)


def validate_reservation(database_url, request_id, symbol, side, quantity, *, increment=QUANTITY_INCREMENT):
    if not database_url or not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Isolated database URL and idempotency key required")
    if not isinstance(symbol, str) or not isinstance(side, str):
        raise ValueError("Invalid symbol or side")
    symbol, side = symbol.strip().upper(), side.strip().upper()
    try:
        qty = Decimal(str(quantity))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid quantity") from None
    if (symbol not in TECH_UNIVERSE or side not in {"BUY", "SELL"} or not qty.is_finite()
            or not 0 < qty < MAX_QUANTITY or qty.quantize(increment) != qty):
        raise ValueError("Invalid reservation")
    return symbol, side, qty


def lock_reservations(cur):
    cur.execute("SET LOCAL lock_timeout = '5s'")
    cur.execute("LOCK TABLE tradebot_v2_order_reservations IN SHARE ROW EXCLUSIVE MODE")


def reserve_offline(database_url: str, request_id: str, symbol: str, side: str, quantity, *, require_idle=False) -> Reservation:
    """Atomically reserve in isolated Neon. Never retries an uncertain database write."""
    symbol, side, qty = validate_reservation(database_url, request_id, symbol, side, quantity)
    # The unique request key and unique active-symbol index are enforced by Postgres.
    # A failed/uncertain connection raises; callers must not treat that as permission.
    import psycopg
    from psycopg import errors
    client_order_id = "offline-" + uuid4().hex
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            lock_reservations(cur)
            cur.execute("""
                SELECT EXISTS (
                    SELECT 1 FROM tradebot_v2_order_reservations
                    WHERE status = ANY(%s)
                    AND (client_order_id NOT LIKE 'offline-%%'
                         OR (%s AND request_id <> %s))
                )
            """, (list(ACTIVE), require_idle, request_id))
            if cur.fetchone()[0]:
                raise RuntimeError("Outstanding durable reservation")
            if require_idle and side == "BUY":
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM tradebot_v2_order_reservations
                        WHERE symbol = %s AND request_id <> %s AND cumulative_filled > 0
                        AND (
                            (side = 'BUY' AND timezone(%s, updated_at)::date
                                = timezone(%s, now())::date)
                            OR (side = 'SELL' AND updated_at > now() - make_interval(hours => %s))
                        )
                    )
                """, (symbol, request_id, MARKET_TIMEZONE.key,
                      MARKET_TIMEZONE.key, COOLDOWN_HOURS))
                if cur.fetchone()[0]:
                    raise RuntimeError("Daily purchase limit or post-sale cooldown active")
            try:
                cur.execute("""
                    INSERT INTO tradebot_v2_order_reservations
                        (request_id, client_order_id, symbol, side, quantity, status)
                    VALUES (%s, %s, %s, %s, %s, 'reserved')
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING request_id, client_order_id, symbol, side, quantity, status, cumulative_filled
                """, (request_id, client_order_id, symbol, side, qty))
                row = cur.fetchone()
                if row is None:
                    cur.execute("""
                        SELECT request_id, client_order_id, symbol, side, quantity, status, cumulative_filled
                        FROM tradebot_v2_order_reservations WHERE request_id = %s
                    """, (request_id,))
                    row = cur.fetchone()
                    if row is None:
                        raise RuntimeError("Reservation state uncertain")
                    if (not row[1].startswith("offline-") or row[2] != symbol
                            or row[3] != side or Decimal(row[4]) != qty):
                        raise ValueError("Idempotency key reused with different payload")
            except errors.UniqueViolation:
                raise RuntimeError("Active order already reserved for this stock") from None
    return Reservation(*row)


def recover_active_offline(database_url: str) -> list[Reservation]:
    """Read all outstanding reservations after restart; fail closed on database errors.

    Caller must reconcile unknown outcomes before creating further reservations.
    This function does not change order status or submit orders.
    """
    if not database_url:
        raise ValueError("Isolated database URL required")
    import psycopg
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT request_id, client_order_id, symbol, side, quantity, status, cumulative_filled
                FROM tradebot_v2_order_reservations
                WHERE status IN ('reserved', 'submitted_unknown', 'accepted', 'partially_filled')
                ORDER BY created_at, request_id
            """)
            rows = cur.fetchall()
    return [Reservation(*row) for row in rows]


def update_offline(database_url: str, request_id: str, status: str, cumulative_filled) -> Reservation:
    """Persist an offline transition under a row lock without creating ownership."""
    if not database_url or not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Isolated database URL and idempotency key required")
    try:
        filled = Decimal(str(cumulative_filled))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid cumulative fill") from None
    if (not isinstance(status, str) or not filled.is_finite()
            or not 0 <= filled < MAX_QUANTITY or filled.quantize(QUANTITY_INCREMENT) != filled):
        raise ValueError("Invalid cumulative fill")

    import psycopg

    with psycopg.connect(database_url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("""
                SELECT request_id, client_order_id, symbol, side, quantity, status, cumulative_filled
                FROM tradebot_v2_order_reservations WHERE request_id = %s FOR UPDATE
            """, (request_id,))
            row = cur.fetchone()
            if row is None or not row[1].startswith("offline-"):
                raise ValueError("Unknown offline reservation")
            order = Reservation(*row)
            if order.status == status and order.cumulative_filled == filled:
                return order
            if status not in TRANSITIONS.get(order.status, frozenset()):
                raise ValueError("Invalid lifecycle transition")
            if not order.cumulative_filled <= filled <= order.quantity:
                raise ValueError("Invalid cumulative fill")
            if status == "filled" and filled != order.quantity:
                raise ValueError("Full fill quantity mismatch")
            if status == "partially_filled" and not 0 < filled < order.quantity:
                raise ValueError("Partial fill quantity mismatch")
            if status in {"submitted_unknown", "accepted", "rejected"} and filled != 0:
                raise ValueError("Unexpected fills for order status")
            if status == "cancelled" and filled == order.quantity:
                raise ValueError("Cancelled order cannot be fully filled")
            cur.execute("""
                UPDATE tradebot_v2_order_reservations
                SET status = %s, cumulative_filled = %s, updated_at = now()
                WHERE request_id = %s
                RETURNING request_id, client_order_id, symbol, side, quantity, status, cumulative_filled
            """, (status, filled, request_id))
            return Reservation(*cur.fetchone())
