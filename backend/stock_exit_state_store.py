"""SQLite position high-watermark and one-shot exit reservation (offline).

This is an isolated testable state primitive. It is NOT connected to the
legacy execution engine or installed as a live trading worker. A reservation
survives process restarts and blocks repeated exit attempts until externally
reconciled. Never assume SQLite on ephemeral storage is restart-durable.
"""
import math
import sqlite3
from pathlib import Path


def _positive(value):
    if isinstance(value, bool):
        raise ValueError("numeric value required")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("invalid numeric value") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError("finite positive value required")
    return result


def _identity(symbol, position_key):
    symbol = str(symbol or "").strip().upper()
    position_key = str(position_key or "").strip()
    if not symbol or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in symbol):
        raise ValueError("invalid symbol")
    if not position_key or len(position_key) > 150 or any(ord(c) < 32 for c in position_key):
        raise ValueError("stable position key required")
    return symbol, position_key


class ExitState:
    def __init__(self, database_path):
        self.database_path = str(Path(database_path))
        if self.database_path == ":memory:":
            raise ValueError("persistent on-disk SQLite required")
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS stock_exit_state (
                symbol TEXT NOT NULL,
                position_key TEXT NOT NULL,
                peak_price REAL NOT NULL CHECK (peak_price > 0),
                reservation TEXT,
                PRIMARY KEY(symbol, position_key)
            )""")

    def _connect(self):
        db = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def observe(self, symbol, position_key, price):
        """Atomically retain highest price ever observed for this position."""
        symbol, position_key = _identity(symbol, position_key)
        value = _positive(price)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT INTO stock_exit_state (symbol, position_key, peak_price)
                   VALUES (?, ?, ?)
                   ON CONFLICT(symbol, position_key) DO UPDATE SET
                   peak_price = MAX(stock_exit_state.peak_price, excluded.peak_price)""",
                (symbol, position_key, value),
            )
            row = db.execute(
                "SELECT peak_price FROM stock_exit_state WHERE symbol=? AND position_key=?",
                (symbol, position_key),
            ).fetchone()
            db.commit()
        return row[0]

    def reserve_once(self, symbol, position_key, reservation_id):
        """Fail closed on existing reservation, including after restart.

        Caller must first record fresh broker position + working order status.
        This reservation is NOT permission to submit an order.
        """
        symbol, position_key = _identity(symbol, position_key)
        reservation_id = str(reservation_id or "").strip()
        if not reservation_id or len(reservation_id) > 150:
            raise ValueError("nonempty reservation id required")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                """UPDATE stock_exit_state SET reservation=?
                   WHERE symbol=? AND position_key=? AND reservation IS NULL""",
                (reservation_id, symbol, position_key),
            )
            db.commit()
            return cursor.rowcount == 1

    def snapshot(self, symbol, position_key):
        symbol, position_key = _identity(symbol, position_key)
        with self._connect() as db:
            row = db.execute(
                """SELECT peak_price, reservation FROM stock_exit_state
                   WHERE symbol=? AND position_key=?""", (symbol, position_key)
            ).fetchone()
        if not row:
            return {"found": False, "peakPrice": None, "reserved": False}
        return {"found": True, "peakPrice": row[0],
                "reserved": row[1] is not None,
                "reservationId": row[1]}

    def clear_after_verified_flat(self, symbol, position_key, *, verified_flat):
        """Clear ONLY when caller provides independently reconciled flat state.

        Do not use for rejected orders without fresh position and order checks.
        """
        if verified_flat is not True:
            raise ValueError("explicit verified_flat=True required")
        symbol, position_key = _identity(symbol, position_key)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute(
                "DELETE FROM stock_exit_state WHERE symbol=? AND position_key=?",
                (symbol, position_key),
            ).rowcount
            db.commit()
        return count == 1
