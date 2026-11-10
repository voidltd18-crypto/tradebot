"""Integration contract: actual coordinator + SQLite journal + mock broker.

No real Alpaca client, no network, and no worker import. Uses the same
SQLite file across a simulated process restart and proves reconciliation
passes the broker_order_id keyword accepted by the real journal.
"""
from decimal import Decimal

from backend.stock_sell_coordinator import SafeStockSellCoordinator
from backend.stock_sell_recovery_disk import open_recovery_on_tradebot_disk


class Broker:
    def __init__(self):
        self.orders = {}
        self.qty = Decimal("10")
        self.submissions = 0
        self.submit_timeout = False
    def fresh_position_qty(self, symbol):
        return self.qty
    def list_open_orders(self, symbol):
        return []
    def get_order_by_client_id(self, cid):
        return self.orders.get(cid)
    def submit_sell(self, symbol, qty, client_order_id):
        self.submissions += 1
        self.orders[client_order_id] = {
            "id": "mock-accepted-sell", "symbol": symbol, "side": "sell",
            "client_order_id": client_order_id, "status": "accepted",
            "filled_qty": "0",
        }
        if self.submit_timeout:
            raise TimeoutError("broker ack lost after accept")
        return self.orders[client_order_id]


def new_coordinator(db, mount, broker):
    return SafeStockSellCoordinator(
        journal=open_recovery_on_tradebot_disk(db, mount_path=mount),
        broker=broker,
    )


def test_accepted_sell_reconciles_through_actual_sqlite_journal(tmp_path):
    mount = tmp_path / "disk"
    mount.mkdir()
    import sqlite3
    db = mount / "trades.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY)")
    broker = Broker()
    first = new_coordinator(db, mount, broker)
    result = first.propose(
        symbol="FMC", position_key="lot-1", quantity="10", eligible=True)
    assert result["status"] == "ACKNOWLEDGED_NOT_FILLED"
    second = new_coordinator(db, mount, broker)
    assert second.propose(
        symbol="FMC", position_key="lot-1", quantity="10",
        eligible=True)["status"] == "RECONCILE_EXISTING"
    assert second.recover(symbol="FMC", position_key="lot-1")["status"] == "WORKING"
    broker.orders[result["clientOrderId"]]["status"] = "partially_filled"
    broker.orders[result["clientOrderId"]]["filled_qty"] = "4"
    broker.qty = Decimal("6")
    assert second.recover(symbol="FMC", position_key="lot-1")["status"] == "PARTIAL"
    broker.orders[result["clientOrderId"]]["status"] = "canceled"
    assert second.recover(
        symbol="FMC", position_key="lot-1")["status"] == "TERMINAL_AWAIT_POSITION"
    assert broker.submissions == 1


def test_timeout_after_broker_accept_recovers_without_duplicate(tmp_path):
    mount = tmp_path / "disk"
    mount.mkdir()
    import sqlite3
    db = mount / "trades.db"
    sqlite3.connect(db).close()
    broker = Broker()
    broker.submit_timeout = True
    first = new_coordinator(db, mount, broker)
    result = first.propose(
        symbol="FMC", position_key="lot-1", quantity=10, eligible=True)
    assert result["status"] == "UNKNOWN_BROKER_OUTCOME"
    broker.submit_timeout = False
    restarted = new_coordinator(db, mount, broker)
    assert restarted.recover(symbol="FMC", position_key="lot-1")["status"] == "WORKING"
    assert not restarted.propose(
        symbol="FMC", position_key="lot-1", quantity=10,
        eligible=True)["submitted"]
    assert broker.submissions == 1
