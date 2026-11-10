"""Run Postgres adapter SQL against a local SQLite compatibility harness.

This verifies SQL semantics for the supported subset; it is NOT a real
PostgreSQL server or production Render durability test.
"""
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from backend.stock_sell_recovery_postgres import PostgresSellRecoveryJournal


SCHEMA = (
    Path(__file__).resolve().parents[1] / "backend/sql"
    / "stock_sell_recovery_postgres_v1.sql"
).read_text(encoding="utf-8")


class CompatConn:
    def __init__(self, filename):
        self.conn = sqlite3.connect(filename, timeout=10)

    def __enter__(self):
        return self

    def __exit__(self, typ, val, tb):
        try:
            if typ:
                self.conn.rollback()
            else:
                self.conn.commit()
        finally:
            self.conn.close()

    def execute(self, query, params=()):
        converted = [str(p) if isinstance(p, Decimal) else p for p in params]
        return self.conn.execute(query.replace("%s", "?"), converted)


def make_journal(tmp_path):
    path = tmp_path / "test.db"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
    return path, PostgresSellRecoveryJournal(lambda: CompatConn(path))


def test_atomic_claims_and_restart(tmp_path):
    path, first = make_journal(tmp_path)
    assert first.reserve_before_submit("FMC", "lot", "attempt-a", 10)
    second = PostgresSellRecoveryJournal(lambda: CompatConn(path))
    assert not second.reserve_before_submit("FMC", "lot", "attempt-b", 10)
    assert second.snapshot("FMC", "lot")["status"] == "RESERVED"
    assert not second.reserve_before_submit("FMC", "other-lot", "attempt-a", 10)


def test_ack_unknown_and_late_recovery(tmp_path):
    path, journal = make_journal(tmp_path)
    journal.reserve_before_submit("FMC", "lot", "attempt", 8)
    assert journal.mark_unknown("FMC", "lot")
    restarted = PostgresSellRecoveryJournal(lambda: CompatConn(path))
    assert not restarted.reserve_before_submit("FMC", "lot", "retry", 8)
    restarted.broker_ack("FMC", "lot", "attempt", "broker-01")
    assert restarted.snapshot("FMC", "lot")["brokerOrderId"] == "broker-01"
    with pytest.raises(ValueError):
        restarted.broker_ack("FMC", "lot", "attempt", "different-order")


def test_partial_then_terminal_cannot_become_working(tmp_path):
    _, journal = make_journal(tmp_path)
    journal.reserve_before_submit("FMC", "lot", "attempt", 10)
    journal.broker_ack("FMC", "lot", "attempt", "broker-01")
    partial = journal.reconcile(
        "FMC", "lot", order_id="broker-01",
        order_status="partially_filled", filled_qty=4, fresh_position_qty=6)
    assert partial["status"] == "PARTIAL"
    terminal = journal.reconcile(
        "FMC", "lot", order_id="broker-01",
        order_status="canceled", filled_qty=4, fresh_position_qty=6)
    assert terminal["status"] == "TERMINAL_AWAIT_POSITION"
    with pytest.raises(ValueError):
        journal.reconcile(
            "FMC", "lot", order_id="broker-01",
            order_status="accepted", filled_qty=4, fresh_position_qty=6)
    assert journal.snapshot("FMC", "lot")["status"] == "TERMINAL_AWAIT_POSITION"


def test_verified_flat_requires_order_terminal_and_zero_position(tmp_path):
    _, journal = make_journal(tmp_path)
    journal.reserve_before_submit("FMC", "lot", "attempt", 10)
    journal.broker_ack("FMC", "lot", "attempt", "broker-01")
    r = journal.reconcile(
        "FMC", "lot", order_id="broker-01", order_status="filled",
        filled_qty=10, fresh_position_qty=2)
    assert r["status"] == "TERMINAL_AWAIT_POSITION"
    r = journal.reconcile(
        "FMC", "lot", order_id="broker-01", order_status="filled",
        filled_qty=10, fresh_position_qty=0)
    assert r["status"] == "VERIFIED_FLAT"
    assert not journal.reserve_before_submit("FMC", "lot", "retry", 10)


def test_mismatch_fill_regression_and_untrusted_status_fail_closed(tmp_path):
    _, journal = make_journal(tmp_path)
    journal.reserve_before_submit("FMC", "lot", "attempt", 10)
    journal.broker_ack("FMC", "lot", "attempt", "broker-01")
    journal.reconcile(
        "FMC", "lot", order_id="broker-01", order_status="partially_filled",
        filled_qty=4, fresh_position_qty=6)
    for values in [
        {"order_id": "wrong", "order_status": "filled", "filled_qty": 10},
        {"order_id": "broker-01", "order_status": "partially_filled", "filled_qty": 2},
        {"order_id": "broker-01", "order_status": "filled", "filled_qty": 5},
        {"order_id": "broker-01", "order_status": "new-unknown", "filled_qty": 4},
    ]:
        with pytest.raises(ValueError):
            journal.reconcile("FMC", "lot", fresh_position_qty=6, **values)
    assert journal.snapshot("FMC", "lot")["filledQty"] == "4"


def test_db_error_fails_closed_instead_of_approving_new_order(tmp_path):
    _, journal = make_journal(tmp_path)
    with sqlite3.connect(tmp_path / "test.db") as db:
        db.execute("DROP TABLE tradebot_stock_sell_recovery_v1")
    with pytest.raises(sqlite3.OperationalError):
        journal.reserve_before_submit("FMC", "lot", "attempt", 10)


def test_invalid_qty_refused(tmp_path):
    _, journal = make_journal(tmp_path)
    for q in [0, -1, "nan", "inf", True]:
        with pytest.raises(ValueError):
            journal.reserve_before_submit("FMC", "lot", "attempt", q)
