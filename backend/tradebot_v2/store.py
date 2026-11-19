"""Optional read-only Postgres ledger reader.

Requires a dedicated TradeBot v2 DATABASE_URL and externally verified fill events.
This module never writes, adopts broker positions, or creates fills.
"""
from backend.tradebot_v2.ledger import OwnershipEvent, reconcile


def read_verified_ownership(database_url: str | None, broker_positions: dict[str, float]):
    if not database_url:
        return reconcile(None, broker_positions)
    try:
        import psycopg
        # Read-only transaction ensures the scanner cannot mutate the ledger.
        with psycopg.connect(database_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
                cur.execute("""
                    SELECT event_id, symbol, broker_order_id, kind, quantity, recorded_at
                    FROM tradebot_v2_fill_events
                    ORDER BY recorded_at, event_id
                """)
                rows = cur.fetchall()
        events = [
            OwnershipEvent(str(row[0]), row[1], str(row[2]), row[3], float(row[4]), row[5])
            for row in rows
        ]
        return reconcile(events, broker_positions)
    except Exception:
        # No fallback to guessing ownership from the broker.
        return reconcile(None, broker_positions)
