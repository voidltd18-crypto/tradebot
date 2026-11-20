"""Durable, offline-only reservation gate for the isolated TradeBot v2 database.

No broker imports, order submission, or ledger writes. Unknown outcomes fail closed.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from uuid import uuid4

TECH = frozenset({"AAPL", "MSFT", "NVDA", "AMZN", "GOOG", "GOOGL", "META"})
ACTIVE = frozenset({"reserved", "submitted_unknown", "accepted", "partially_filled"})


@dataclass(frozen=True)
class Reservation:
    request_id: str
    client_order_id: str
    symbol: str
    side: str
    quantity: Decimal
    status: str


def reserve_offline(database_url: str, request_id: str, symbol: str, side: str, quantity) -> Reservation:
    """Atomically reserve in isolated Neon. Never retries an uncertain database write."""
    if not database_url or not isinstance(request_id, str) or not request_id.strip():
        raise ValueError("Isolated database URL and idempotency key required")
    if not isinstance(symbol, str) or not isinstance(side, str):
        raise ValueError("Invalid symbol or side")
    symbol, side = symbol.strip().upper(), side.strip().upper()
    try:
        qty = Decimal(str(quantity))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid quantity") from None
    if symbol not in TECH or side not in {"BUY", "SELL"} or not qty.is_finite() or qty <= 0:
        raise ValueError("Invalid offline reservation")
    # The unique request key and unique active-symbol index are enforced by Postgres.
    # A failed/uncertain connection raises; callers must not treat that as permission.
    import psycopg
    from psycopg import errors
    client_order_id = "offline-" + uuid4().hex
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            try:
                cur.execute("""
                    INSERT INTO tradebot_v2_order_reservations
                        (request_id, client_order_id, symbol, side, quantity, status)
                    VALUES (%s, %s, %s, %s, %s, 'reserved')
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING request_id, client_order_id, symbol, side, quantity, status
                """, (request_id, client_order_id, symbol, side, qty))
                row = cur.fetchone()
                if row is None:
                    cur.execute("""
                        SELECT request_id, client_order_id, symbol, side, quantity, status
                        FROM tradebot_v2_order_reservations WHERE request_id = %s
                    """, (request_id,))
                    row = cur.fetchone()
                    if row is None:
                        raise RuntimeError("Reservation state uncertain")
                    if row[2] != symbol or row[3] != side or Decimal(row[4]) != qty:
                        raise ValueError("Idempotency key reused with different payload")
            except errors.UniqueViolation:
                raise RuntimeError("Active order already reserved for this stock") from None
    return Reservation(str(row[0]), str(row[1]), row[2], row[3], Decimal(row[4]), row[5])


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
                SELECT request_id, client_order_id, symbol, side, quantity, status
                FROM tradebot_v2_order_reservations
                WHERE status IN ('reserved', 'submitted_unknown', 'accepted', 'partially_filled')
                ORDER BY created_at, request_id
            """)
            rows = cur.fetchall()
    return [Reservation(str(row[0]), str(row[1]), row[2], row[3],
                        Decimal(row[4]), row[5]) for row in rows]
