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
        self.broker = SimpleNamespace(
            get_account=lambda: SimpleNamespace(id=self.account),
            get_all_positions=lambda: [SimpleNamespace(symbol="MSFT", qty=self.qty)],
            get_order_by_client_id=lambda client_id: self.order,
            get=lambda *args, **kwargs: self.activities,
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
        with self.assertRaises(sqlite3.IntegrityError):
            reserve_stock_purchase(self.connect, self.broker, "MSFT", 100, self.account)
