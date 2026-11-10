"""No live broker/network: read-only audit of existing journal records."""
import sqlite3
from decimal import Decimal
from backend.stock_sell_startup_audit import audit_stock_sell_recovery
from backend.stock_sell_coordinator import stable_client_order_id


class Broker:
    def __init__(self, *, status="accepted", position=10, lookup_error=None):
        self.status = status
        self.position = position
        self.lookup_error = lookup_error
        self.lookups = 0
    def get_order_by_client_id(self, client_id):
        self.lookups += 1
        if self.lookup_error:
            raise ConnectionError("mock Alpaca connection failed")
        return {"id": "broker-1", "symbol": "FMC", "side": "sell",
                "client_order_id": client_id,
                "status": self.status, "filled_qty": "0"}
    def fresh_position_qty(self, symbol):
        return Decimal(self.position)


def setup_db(tmp_path):
    path = tmp_path / "trades.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE stock_sell_recovery (
          symbol TEXT, position_key TEXT, attempt_id TEXT,
          intended_qty REAL, broker_order_id TEXT, status TEXT,
          filled_qty REAL)""")
        db.execute("INSERT INTO stock_sell_recovery VALUES (?,?,?,?,?,?,?)",
                   ("FMC", "lot-1", stable_client_order_id("FMC", "lot-1"),
                    10, "broker-1", "UNKNOWN", 0))
    return path


def test_missing_recovery_schema_is_read_only(tmp_path):
    db = tmp_path / "trades.db"
    sqlite3.connect(db).close()
    result = audit_stock_sell_recovery(db, broker=Broker())
    assert result["journalPresent"] is False
    assert result["ordersSubmitted"] == 0
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0] == 0


def test_unknown_ack_is_review_only(tmp_path):
    result = audit_stock_sell_recovery(setup_db(tmp_path), broker=Broker())
    assert result["needsReview"]
    assert result["rows"][0]["result"] == "OPEN_OR_PARTIAL_REVIEW"
    assert result["rows"][0]["blocked"] is True


def test_timeout_stays_blocked_and_db_row_unchanged(tmp_path):
    path = setup_db(tmp_path)
    result = audit_stock_sell_recovery(path, broker=Broker(lookup_error=True))
    assert result["rows"][0]["result"] == "BROKER_READ_FAILED"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM stock_sell_recovery").fetchone()[0] == "UNKNOWN"


def test_terminal_flat_requires_manual_review(tmp_path):
    result = audit_stock_sell_recovery(
        setup_db(tmp_path), broker=Broker(status="filled", position=0))
    assert result["rows"][0]["result"] == "TERMINAL_AND_FLAT_REVIEW"
    assert result["rows"][0]["blocked"] is True


def test_recorded_attempt_mismatch_does_not_call_broker(tmp_path):
    path = setup_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE stock_sell_recovery SET attempt_id='other'")
    broker = Broker()
    result = audit_stock_sell_recovery(path, broker=broker)
    assert result["rows"][0]["result"] == "ATTEMPT_ID_MISMATCH"
    assert broker.lookups == 0
