"""Optional read-only Postgres ledger reader.

Requires a dedicated TradeBot v2 DATABASE_URL and externally verified fill events.
This module never writes, adopts broker positions, or creates fills.
"""
from uuid import UUID

from backend.tradebot_v2.ledger import OwnershipEvent, reconcile


def read_verified_ownership(database_url: str | None, broker_positions: dict[str, float],
                            *, account_id: UUID | None = None):
    if not database_url or not isinstance(account_id, UUID):
        return reconcile(None, broker_positions)
    try:
        import psycopg
        # Read-only transaction ensures the scanner cannot mutate the ledger.
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("""
                    SELECT f.event_id, f.symbol, f.broker_order_id, f.kind, f.quantity, f.recorded_at
                    FROM tradebot_v2_fill_events AS f
                    JOIN tradebot_v2_order_reservations AS r ON r.request_id = f.reservation_id
                    WHERE f.account_id = %s AND r.account_id = f.account_id
                      AND r.broker_order_id::text = f.broker_order_id
                      AND r.symbol = f.symbol AND r.side || '_FILLED' = f.kind
                    ORDER BY f.recorded_at, f.event_id
                """, (account_id,))
                rows = cur.fetchall()
        events = [
            OwnershipEvent(str(row[0]), row[1], str(row[2]), row[3], float(row[4]), row[5])
            for row in rows
        ]
        return reconcile(events, broker_positions)
    except Exception:
        # No fallback to guessing ownership from the broker.
        return reconcile(None, broker_positions)
