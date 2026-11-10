"""Offline, fail-closed journal for a broker-acknowledged stock sell.

NO broker calls or automatic order submission. This prototype is explicitly
NOT wired into the live stock worker. Its database MUST reside on truly durable
shared storage before production use: ephemeral container SQLite is unsuitable.

A reservation is written BEFORE an attempted order. If the submit result is
unknown, do not retry until an authoritative broker reconciliation occurs.
"""
import math
import sqlite3
from pathlib import Path

from backend.stock_exit_state_store import _identity, _positive
from backend.stock_exit_paper_rehearsal import WORKING, TERMINAL


class SellRecoveryJournal:
    def __init__(self, path):
        self.path = str(Path(path))
        if self.path == ":memory:":
            raise ValueError("durable on-disk journal is required")
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS stock_sell_recovery (
                symbol TEXT NOT NULL,
                position_key TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                intended_qty REAL NOT NULL CHECK (intended_qty > 0),
                broker_order_id TEXT,
                status TEXT NOT NULL CHECK(status IN
                  ('RESERVED','ACKNOWLEDGED','UNKNOWN','WORKING','PARTIAL',
                   'TERMINAL_AWAIT_POSITION','VERIFIED_FLAT')),
                filled_qty REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(symbol, position_key),
                UNIQUE(attempt_id)
            )""")

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def reserve_before_submit(self, symbol, position_key, attempt_id, qty):
        """True only for the very first claim; repeat attempts never submit."""
        symbol, position_key = _identity(symbol, position_key)
        attempt_id = str(attempt_id or "").strip()
        if not attempt_id or len(attempt_id) > 150:
            raise ValueError("stable attempt ID required")
        qty = _positive(qty)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM stock_sell_recovery WHERE symbol=? AND position_key=?",
                (symbol, position_key)).fetchone()
            if row:
                db.commit()
                return False
            try:
                db.execute(
                    """INSERT INTO stock_sell_recovery
                       (symbol,position_key,attempt_id,intended_qty,status)
                       VALUES (?,?,?,?,'RESERVED')""",
                    (symbol, position_key, attempt_id, qty))
            except sqlite3.IntegrityError:
                db.rollback()
                return False
            db.commit()
            return True

    def broker_ack(self, symbol, position_key, attempt_id, order_id):
        """Record accepted order ID; no second submit and no realised P&L."""
        symbol, position_key = _identity(symbol, position_key)
        if not isinstance(order_id, str) or not order_id.strip() or len(order_id) > 150:
            raise ValueError("broker order ID required")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT attempt_id, broker_order_id, status FROM stock_sell_recovery "
                "WHERE symbol=? AND position_key=?", (symbol, position_key)
            ).fetchone()
            if not row or row[0] != attempt_id or (row[1] and row[1] != order_id):
                db.rollback()
                raise ValueError("unknown or mismatched sell attempt")
            if row[2] not in {"RESERVED", "UNKNOWN", "ACKNOWLEDGED", "WORKING"}:
                db.rollback()
                raise ValueError("cannot acknowledge terminal sell attempt")
            db.execute(
                """UPDATE stock_sell_recovery SET status='ACKNOWLEDGED',
                   broker_order_id=? WHERE symbol=? AND position_key=?""",
                (order_id, symbol, position_key))
            db.commit()

    def mark_unknown(self, symbol, position_key):
        """Used when submit timed out or pending registration failed.

        This is NOT an order rejection. Keep symbol blocked until broker
        lookup resolves the ambiguity, even after process restart.
        """
        symbol, position_key = _identity(symbol, position_key)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                """UPDATE stock_sell_recovery SET status='UNKNOWN'
                   WHERE symbol=? AND position_key=?
                   AND status IN ('RESERVED','ACKNOWLEDGED','WORKING')""",
                (symbol, position_key)).rowcount
            db.commit()
            return count == 1

    def reconcile(self, symbol, position_key, *, broker_order_id, order_status,
                  filled_qty, fresh_position_qty):
        """Reconcile authoritative broker order AND position snapshots.

        Canceled/rejected orders may still have partial fills. No further
        submission is permitted here, even after terminal status.
        """
        symbol, position_key = _identity(symbol, position_key)
        status = str(order_status or "").lower()
        if status not in WORKING | TERMINAL:
            raise ValueError("unknown broker order status")
        fill, remaining = float(filled_qty), float(fresh_position_qty)
        if not all(math.isfinite(v) and v >= 0 for v in (fill, remaining)):
            raise ValueError("invalid authoritative quantities")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT broker_order_id, intended_qty, filled_qty, status
                   FROM stock_sell_recovery
                   WHERE symbol=? AND position_key=?""",
                (symbol, position_key)).fetchone()
            if not row or not broker_order_id or (
                row[0] and row[0] != broker_order_id
            ):
                db.rollback()
                raise ValueError("unverified order identity")
            if fill > row[1] + 1e-8 or fill + 1e-8 < row[2]:
                db.rollback()
                raise ValueError("inconsistent cumulative fills")
            if status == "filled" and abs(fill - row[1]) > 1e-8:
                db.rollback()
                raise ValueError("filled order quantity mismatch")
            if row[3] == "TERMINAL_AWAIT_POSITION" and status not in TERMINAL:
                db.rollback()
                raise ValueError("terminal broker order cannot return to working")
            if row[3] == "VERIFIED_FLAT":
                db.rollback()
                raise ValueError("already verified flat")
            resolved = ("VERIFIED_FLAT" if status in TERMINAL and remaining == 0
                        else "TERMINAL_AWAIT_POSITION" if status in TERMINAL
                        else "PARTIAL" if fill > 0 else "WORKING")
            db.execute(
                """UPDATE stock_sell_recovery
                   SET broker_order_id=?, filled_qty=?, status=?
                   WHERE symbol=? AND position_key=?""",
                (broker_order_id, fill, resolved, symbol, position_key))
            db.commit()
            return {"status": resolved, "blockedFromResubmit": True,
                    "brokerFilledQty": fill, "freshPositionQty": remaining}

    def snapshot(self, symbol, position_key):
        symbol, position_key = _identity(symbol, position_key)
        with self._db() as db:
            row = db.execute(
                """SELECT attempt_id, intended_qty, broker_order_id,
                          status, filled_qty FROM stock_sell_recovery
                   WHERE symbol=? AND position_key=?""",
                (symbol, position_key)).fetchone()
        return ({"found": False, "blockedFromResubmit": False} if not row else
                {"found": True, "attemptId": row[0], "intendedQty": row[1],
                 "brokerOrderId": row[2], "status": row[3],
                 "filledQty": row[4], "blockedFromResubmit": True})
