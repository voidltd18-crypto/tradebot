"""Experimental PostgreSQL-backed sell recovery journal (NOT live-wired).

Requires previously reviewed migration sql/stock_sell_recovery_postgres_v1.sql.
Caller injects a psycopg connection factory; no credentials, environment
variables or broker transport are read here. SQL is atomic per statement;
all uncertainty leaves the same position blocked until independently resolved.

A durable *shared* database is necessary but not sufficient for live safety:
the order submission path still needs broker-side idempotent client_order_id,
startup reconciliation, worker ownership and verified deployed configuration.
"""
from decimal import Decimal, InvalidOperation
from math import isfinite

from backend.stock_exit_state_store import _identity
from backend.stock_exit_paper_rehearsal import KNOWN, TERMINAL


def _qty(value, *, allow_zero=False):
    if isinstance(value, bool):
        raise ValueError("quantity must be numeric")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid quantity") from None
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise ValueError("quantity must be finite and positive")
    return number


def _token(value, label):
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 150:
        raise ValueError(label + " required")
    return value.strip()


class PostgresSellRecoveryJournal:
    def __init__(self, connection_factory):
        if not callable(connection_factory):
            raise ValueError("connection factory required")
        self._connect = connection_factory

    def reserve_before_submit(self, symbol, position_key, attempt_id, qty):
        symbol, position_key = _identity(symbol, position_key)
        attempt_id = _token(attempt_id, "attempt ID")
        qty = _qty(qty)
        # Fail-closed: a UNIQUE violation or DB outage must propagate; do NOT
        # interpret it as permission to retry a broker submission.
        with self._connect() as conn:
            row = conn.execute(
                """INSERT INTO tradebot_stock_sell_recovery_v1
                   (symbol,position_key,attempt_id,intended_qty,status)
                   VALUES (%s,%s,%s,%s,'RESERVED')
                   ON CONFLICT DO NOTHING RETURNING attempt_id""",
                (symbol, position_key, attempt_id, qty)).fetchone()
            return bool(row)

    def broker_ack(self, symbol, position_key, attempt_id, order_id):
        symbol, position_key = _identity(symbol, position_key)
        attempt_id = _token(attempt_id, "attempt ID")
        order_id = _token(order_id, "order ID")
        with self._connect() as conn:
            row = conn.execute(
                """UPDATE tradebot_stock_sell_recovery_v1
                   SET broker_order_id=%s, status='ACKNOWLEDGED'
                   WHERE symbol=%s AND position_key=%s AND attempt_id=%s
                     AND status IN ('RESERVED','UNKNOWN','ACKNOWLEDGED','WORKING')
                     AND (broker_order_id IS NULL OR broker_order_id=%s)
                   RETURNING attempt_id""",
                (order_id, symbol, position_key, attempt_id, order_id)).fetchone()
            if not row:
                raise ValueError("unverified or already terminal sell acknowledgement")

    def mark_unknown(self, symbol, position_key):
        symbol, position_key = _identity(symbol, position_key)
        with self._connect() as conn:
            row = conn.execute(
                """UPDATE tradebot_stock_sell_recovery_v1 SET status='UNKNOWN'
                   WHERE symbol=%s AND position_key=%s
                     AND status IN ('RESERVED','ACKNOWLEDGED','WORKING')
                   RETURNING attempt_id""",
                (symbol, position_key)).fetchone()
            return bool(row)

    def reconcile(self, symbol, position_key, *, broker_order_id, order_status,
                  filled_qty, fresh_position_qty):
        symbol, position_key = _identity(symbol, position_key)
        order_id = _token(broker_order_id, "order ID")
        status = str(order_status or "").strip().lower()
        if status not in KNOWN:
            raise ValueError("unrecognized broker order status")
        fill = _qty(filled_qty, allow_zero=True)
        position = _qty(fresh_position_qty, allow_zero=True)
        # A single compare-and-set statement rejects mismatched order IDs,
        # non-monotonic cumulative fills, or impossible full-fill claims.
        target = ("VERIFIED_FLAT" if status in TERMINAL and position == 0
                  else "TERMINAL_AWAIT_POSITION" if status in TERMINAL
                  else "PARTIAL" if fill > 0 else "WORKING")
        with self._connect() as conn:
            row = conn.execute(
                """UPDATE tradebot_stock_sell_recovery_v1
                   SET broker_order_id=%s, filled_qty=%s, status=%s
                   WHERE symbol=%s AND position_key=%s
                     AND (broker_order_id IS NULL OR broker_order_id=%s)
                     AND status != 'VERIFIED_FLAT'
                     AND (status != 'TERMINAL_AWAIT_POSITION' OR
                          %s IN ('filled','canceled','expired','rejected','replaced'))
                     AND filled_qty <= %s AND intended_qty >= %s
                     AND (%s != 'filled' OR intended_qty = %s)
                   RETURNING attempt_id""",
                (order_id, fill, target, symbol, position_key, order_id,
                 status, fill, fill, status, fill)).fetchone()
            if not row:
                raise ValueError("unverified, inconsistent or already terminal sell")
        return {"status": target, "blockedFromResubmit": True,
                "brokerFilledQty": str(fill), "freshPositionQty": str(position)}

    def snapshot(self, symbol, position_key):
        symbol, position_key = _identity(symbol, position_key)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT attempt_id,intended_qty,broker_order_id,status,filled_qty
                   FROM tradebot_stock_sell_recovery_v1
                   WHERE symbol=%s AND position_key=%s""",
                (symbol, position_key)).fetchone()
        if not row:
            return {"found": False, "blockedFromResubmit": False}
        return {"found": True, "attemptId": row[0],
                "intendedQty": str(row[1]), "brokerOrderId": row[2],
                "status": row[3], "filledQty": str(row[4]),
                "blockedFromResubmit": True}
