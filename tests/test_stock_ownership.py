from datetime import datetime, timezone
from decimal import Decimal
import sqlite3
from types import SimpleNamespace
import unittest

from backend.stock_ownership import init_stock_ownership, reserve_stock_purchase, verified_stock_quantity


class StockOwnershipTests(unittest.TestCase):
    def setUp(self):
        from tempfile import TemporaryDirectory

        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = directory.name + "/ownership.db"
        with self.connect() as conn:
            init_stock_ownership(conn)

        self.qty = "0"
        self.account = "fixture-account"
        self.activities = []
        self.open_orders = []
        self.order = None
        self.broker = SimpleNamespace(
            get_account=lambda: SimpleNamespace(id=self.account),
            get_all_positions=lambda: [SimpleNamespace(symbol="MSFT", qty=self.qty)],
            get_order_by_client_id=lambda client_id: self.order,
            get=lambda path, **kwargs: self.open_orders if path == "/orders" else self.activities,
        )

    def connect(self):
        return sqlite3.connect(self.path)

    def own_one_share(self):
        client_id = reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
        self.qty = "1.000000001"
        self.order = SimpleNamespace(
            client_order_id=client_id, id="fixture-order", symbol="MSFT", side="buy",
            status="filled", notional="100", filled_qty=self.qty,
            created_at=datetime.now(timezone.utc),
        )
        fill = dict(activity_type="FILL", order_id=self.order.id, symbol="MSFT", side="buy")
        self.activities = [
            dict(fill, id="second", qty="1", cum_qty="1.000000001"),
            dict(fill, id="first", qty="0.000000001", cum_qty="0.000000001"),
        ]

    def verify(self):
        return verified_stock_quantity(self.connect, self.broker, "MSFT")

    def test_existing_holdings_are_ineligible(self):
        self.qty = "1"
        self.assertIsNone(self.verify())
        with self.assertRaises(ValueError):
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)

    def test_exact_fills_survive_new_connections_and_duplicate_activity(self):
        self.own_one_share()
        self.activities.append(self.activities[0].copy())
        self.assertEqual(self.verify(), Decimal("1.000000001"))
        self.assertEqual(self.verify(), Decimal("1.000000001"))

    def test_same_quantity_does_not_prove_ownership_after_manual_trade(self):
        self.own_one_share()
        self.activities.append(dict(self.activities[0], id="manual", order_id="manual-order"))
        self.assertIsNone(self.verify())

    def test_missing_activity_and_wrong_account_block(self):
        self.own_one_share()
        self.activities = self.activities[:1]
        self.assertIsNone(self.verify())
        self.account = "another-account"
        self.assertIsNone(self.verify())

    def test_unresolved_intent_cannot_be_replaced(self):
        reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
        with self.assertRaises(ValueError):
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)

    def test_terminal_zero_fill_can_be_archived(self):
        for status in ("canceled", "expired", "rejected"):
            with self.subTest(status=status):
                with self.connect() as conn:
                    conn.execute("DELETE FROM stock_ownership_intents")
                previous = reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
                self.order = SimpleNamespace(
                    client_order_id=previous, id="fixture-order", symbol="MSFT", side="buy",
                    status=status, notional="100", filled_qty="0",
                    created_at=datetime.now(timezone.utc),
                )
                replacement = reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
                self.assertNotEqual(previous, replacement)
                with self.connect() as conn:
                    archived = conn.execute(
                        "SELECT evidence FROM stock_ownership_resolutions WHERE client_order_id = ?",
                        (previous,),
                    ).fetchone()
                    self.assertIn(status, archived[0])

    def test_partial_fill_requires_complete_flat_lifecycle(self):
        self.own_one_share()
        self.order.status = "canceled"
        self.order.filled_qty = self.qty = "0.000000001"
        with self.assertRaises(ValueError):
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
        self.qty = "0"
        from datetime import timedelta
        stamp = datetime.now(timezone.utc)
        bought = dict(self.activities[1], transaction_time=stamp.isoformat())
        self.activities = [bought]
        with self.assertRaises(ValueError):
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
        self.activities.append(dict(bought, id="exit", order_id="exit-order", side="sell",
                                    transaction_time=(stamp + timedelta(seconds=1)).isoformat()))
        self.open_orders = [{"id": "still-open", "symbol": "MSFT"}]
        with self.assertRaises(ValueError):
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
        self.open_orders = []
        self.assertNotEqual(
            self.order.client_order_id,
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account),
        )

    def test_open_orders_block_sell_ownership(self):
        self.own_one_share()
        self.open_orders = [{"id": "sell-already-open", "symbol": "MSFT"}]
        self.assertIsNone(self.verify())

    def test_two_workers_cannot_replace_one_resolved_intent(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        previous = reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
        self.order = SimpleNamespace(
            client_order_id=previous, id="fixture-order", symbol="MSFT", side="buy",
            status="expired", notional="100", filled_qty="0",
            created_at=datetime.now(timezone.utc),
        )
        ready = Barrier(2)

        def get_order(_):
            ready.wait(timeout=3)
            return self.order

        self.broker.get_order_by_client_id = get_order

        def replace():
            try:
                return reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts = [pool.submit(replace) for _ in range(2)]
            self.assertEqual(sum(attempt.result() is not None for attempt in attempts), 1)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM stock_ownership_resolutions").fetchone()[0], 1)

    def test_delayed_order_and_broker_timeout_leave_intent_in_place(self):
        self.own_one_share()
        self.qty = "0"
        self.order.status = "partially_filled"
        with self.assertRaises(ValueError):
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)

        def timed_out(_):
            raise TimeoutError()

        self.broker.get_order_by_client_id = timed_out
        with self.assertRaises(ValueError):
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT client_order_id FROM stock_ownership_intents").fetchone()[0],
                             self.order.client_order_id)
