"""Offline contract tests: zero external calls, zero real broker orders."""
from decimal import Decimal
from backend.stock_sell_coordinator import SafeStockSellCoordinator, stable_client_order_id


class Journal:
    def __init__(self):
        self.rows = {}
        self.fail_ack = False
    def snapshot(self, symbol, key):
        return {"found": (symbol, key) in self.rows}
    def reserve_before_submit(self, symbol, key, cid, qty):
        if (symbol, key) in self.rows:
            return False
        self.rows[(symbol, key)] = {"attempt": cid, "qty": qty, "status": "RESERVED"}
        return True
    def mark_unknown(self, symbol, key):
        self.rows[(symbol, key)]["status"] = "UNKNOWN"
        return True
    def broker_ack(self, symbol, key, cid, oid):
        if self.fail_ack:
            raise OSError("mock durable DB outage")
        self.rows[(symbol, key)].update(status="ACKNOWLEDGED", order_id=oid)
    def reconcile(self, symbol, key, **kw):
        self.rows[(symbol, key)]["status"] = "VERIFIED_FLAT"
        return {"status": "VERIFIED_FLAT"}


class Broker:
    def __init__(self):
        self.orders = []
        self.present = None
        self.quantity = Decimal("10")
        self.open_orders = []
        self.fail = False
        self.lookup_error = False
    def fresh_position_qty(self, symbol):
        return self.quantity
    def list_open_orders(self, symbol):
        return self.open_orders
    def get_order_by_client_id(self, cid):
        if self.lookup_error:
            raise OSError("broker status unavailable")
        return self.present
    def submit_sell(self, symbol, qty, client_order_id):
        self.orders.append((symbol, qty, client_order_id))
        if self.fail:
            # Mimics timeout AFTER an accepted order.
            self.present = {"id": "broker-1", "symbol": symbol, "side": "sell", "client_order_id": client_order_id,
                            "status": "accepted", "filled_qty": "0"}
            raise TimeoutError("ack timeout")
        self.present = {"id": "broker-1", "client_order_id": client_order_id,
                        "status": "accepted", "filled_qty": "0"}
        return self.present


def make():
    j, b = Journal(), Broker()
    return SafeStockSellCoordinator(journal=j, broker=b), j, b


def test_client_id_deterministic_not_random():
    assert stable_client_order_id("fmc", "lot") == stable_client_order_id("FMC", "lot")
    assert stable_client_order_id("FMC", "different") != stable_client_order_id("FMC", "lot")


def test_acknowledgment_once_never_implies_fill_or_resubmits():
    c, j, b = make()
    result = c.propose(symbol="FMC", position_key="lot", quantity="10", eligible=True)
    assert result["status"] == "ACKNOWLEDGED_NOT_FILLED"
    assert len(b.orders) == 1
    assert c.propose(symbol="FMC", position_key="lot", quantity="10",
                     eligible=True)["status"] == "RECONCILE_EXISTING"
    assert len(b.orders) == 1


def test_timeout_after_broker_accept_stays_reserved_after_restart():
    c, j, b = make()
    b.fail = True
    assert c.propose(symbol="FMC", position_key="lot", quantity=10,
                     eligible=True)["status"] == "UNKNOWN_BROKER_OUTCOME"
    assert j.rows[("FMC", "lot")]["status"] == "UNKNOWN"
    restarted = SafeStockSellCoordinator(journal=j, broker=b)
    assert restarted.propose(symbol="FMC", position_key="lot", quantity=10,
                             eligible=True)["status"] == "RECONCILE_EXISTING"
    assert len(b.orders) == 1
    b.quantity = Decimal("0")
    assert restarted.recover(symbol="FMC", position_key="lot")["status"] == "VERIFIED_FLAT"
    assert len(b.orders) == 1


def test_persistence_error_never_causes_second_sell():
    c, j, b = make()
    j.fail_ack = True
    assert c.propose(symbol="FMC", position_key="lot", quantity=10,
                     eligible=True)["status"] == "ACK_PERSISTENCE_UNCERTAIN"
    assert len(b.orders) == 1
    assert c.propose(symbol="FMC", position_key="lot", quantity=10,
                     eligible=True)["status"] == "RECONCILE_EXISTING"
    assert len(b.orders) == 1


def test_fresh_broker_unknown_prevents_submission():
    c, j, b = make()
    b.lookup_error = True
    import pytest
    with pytest.raises(OSError):
        c.propose(symbol="FMC", position_key="lot", quantity=10, eligible=True)
    assert not b.orders and not j.rows


def test_preflight_checks_prevent_sells():
    c, j, b = make()
    assert c.propose(symbol="FMC", position_key="lot", quantity=10)["status"] == "BLOCKED_PRECHECK"
    b.open_orders = [{"side": "sell"}]
    assert c.propose(symbol="FMC", position_key="lot", quantity=10,
                     eligible=True)["status"] == "BLOCKED_EXISTING_SELL"
    b.open_orders = []
    b.quantity = Decimal("8")
    assert c.propose(symbol="FMC", position_key="lot", quantity=10,
                     eligible=True)["status"] == "BLOCKED_POSITION_MISMATCH"
    assert not j.rows and not b.orders


def test_known_broker_id_before_reservation_blocks_trade():
    c, j, b = make()
    b.present = {"id": "old", "symbol": "FMC", "side": "sell", "client_order_id": stable_client_order_id("FMC", "lot")}
    assert c.propose(symbol="FMC", position_key="lot", quantity=10,
                     eligible=True)["status"] == "BROKER_ORDER_EXISTS"
    assert not j.rows and not b.orders


def test_missing_broker_ack_does_not_unlock_reservation():
    c, j, b = make()
    b.fail = True
    c.propose(symbol="FMC", position_key="lot", quantity=10, eligible=True)
    b.present = None
    assert c.recover(symbol="FMC", position_key="lot")["status"] == "UNRESOLVED_BROKER_ORDER"
    assert len(b.orders) == 1
    assert j.rows[("FMC", "lot")]["status"] == "UNKNOWN"
