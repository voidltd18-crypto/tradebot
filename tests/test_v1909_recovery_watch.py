"""Regression tests for V19.0.9 watch reconciliation (no real broker)."""
import unittest
from unittest.mock import patch
from backend import v18375_stock_recovery_watch as rw

class FakeBroker:
    def __init__(self):
        self.price = 98.0
        self.positions = [{"symbol":"TEST","price":self.price}]
        self.sells = []
    def get_all_positions(self):
        return [{"symbol":"TEST","price":self.price}]
    def get_quote(self,symbol):
        return {"mid":self.price}
    def market_sell_qty(self,symbol,qty,*args,**kwargs):
        self.sells.append((symbol,qty))
        return True

class WatchTests(unittest.TestCase):
    def setUp(self):
        rw._watch.clear()
        rw._grandfathered_symbols.clear()

    def tearDown(self):
        rw._watch.clear()
        rw._grandfathered_symbols.clear()

    def test_two_confirmations_clear_without_selling(self):
        m=FakeBroker()
        with patch.object(rw,"_fresh_quote_price",side_effect=lambda broker,symbol:broker.price):
            rw.install_v18375_stock_recovery_watch(None,m)
            rw._watch["TEST"]={"entryPrice":100.0,"startedAt":1,"deadline":1000000000.0}
            m.price=99.0
            m.get_all_positions()
            self.assertIn("TEST",rw._watch)
            m.get_all_positions()
            self.assertNotIn("TEST",rw._watch)
            self.assertEqual(m.sells,[])

    def test_single_recovery_then_loss_does_not_clear(self):
        m=FakeBroker()
        with patch.object(rw,"_fresh_quote_price",side_effect=lambda broker,symbol:broker.price):
            rw.install_v18375_stock_recovery_watch(None,m)
            rw._watch["TEST"]={"entryPrice":100.0,"startedAt":1,"deadline":1000000000.0}
            m.price=99.0
            m.get_all_positions()
            m.price=97.0
            m.get_all_positions()
            self.assertIn("TEST",rw._watch)
            self.assertEqual(rw._watch["TEST"].get("recoveryPolls"),0)
            self.assertEqual(m.sells,[])

if __name__=="__main__":
    unittest.main()
