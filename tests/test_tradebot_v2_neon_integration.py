"""Opt-in Neon integration tests; transactions always roll back.

Requires TRADEBOT_V2_TEST_DATABASE_URL pointing at the isolated test database.
No broker calls. Never run against production or the original TradeBot database.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest

URL = (os.getenv("TRADEBOT_V2_TEST_DATABASE_URL")
       if os.getenv("TRADEBOT_V2_DISPOSABLE_TEST_BRANCH") == "true" else None)


@pytest.mark.skipif(not URL, reason="Isolated Neon integration test URL not configured")
def test_idempotency_and_active_symbol_uniqueness():
    import psycopg
    from psycopg import errors
    key = "integration-" + uuid4().hex
    with psycopg.connect(URL, connect_timeout=5) as conn:
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO tradebot_v2_order_reservations
                    (request_id, client_order_id, symbol, side, quantity)
                    VALUES (%s, %s, 'MSFT', 'BUY', 1)
                """, (key, key))
                cur.execute("""
                    INSERT INTO tradebot_v2_order_reservations
                    (request_id, client_order_id, symbol, side, quantity)
                    VALUES (%s, %s, 'MSFT', 'BUY', 1)
                    ON CONFLICT (request_id) DO NOTHING
                    RETURNING request_id
                """, (key, key))
                assert cur.fetchone() is None
                # Savepoint prevents expected unique violation aborting the test transaction.
                cur.execute("SAVEPOINT duplicate_symbol")
                with pytest.raises(errors.UniqueViolation):
                    cur.execute("""
                        INSERT INTO tradebot_v2_order_reservations
                        (request_id, client_order_id, symbol, side, quantity)
                        VALUES (%s, %s, 'MSFT', 'SELL', 1)
                    """, (key + "-other", key + "-other"))
                cur.execute("ROLLBACK TO SAVEPOINT duplicate_symbol")
                cur.execute("""
                    SELECT COUNT(*) FROM tradebot_v2_order_reservations
                    WHERE request_id = %s
                """, (key,))
                assert cur.fetchone()[0] == 1
        finally:
            conn.rollback()


@pytest.mark.skipif(not URL, reason="Isolated Neon integration test URL not configured")
def test_reservation_survives_new_connection_only_after_commit():
    """Rollback-only test: a second connection must not see an uncommitted reservation."""
    import psycopg
    key = "integration-" + uuid4().hex
    with psycopg.connect(URL, connect_timeout=5) as writer:
        try:
            with writer.cursor() as cur:
                cur.execute("""
                    INSERT INTO tradebot_v2_order_reservations
                    (request_id, client_order_id, symbol, side, quantity)
                    VALUES (%s, %s, 'GOOGL', 'BUY', 1)
                """, (key, key))
            with psycopg.connect(URL, connect_timeout=5) as reader:
                with reader.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM tradebot_v2_order_reservations WHERE request_id = %s", (key,))
                    assert cur.fetchone()[0] == 0
        finally:
            writer.rollback()
