import unittest
from types import SimpleNamespace
from backend import v19011_sell_telemetry as t

class FakeApp:
    def get(self,path):
        def register(fn): return fn
        return register

class TelemetryTests(unittest.TestCase):
    def setUp(self): t._events.clear()
    def test_preserves_result_and_arguments(self):
        received=[]
        def sell(*args,**kwargs):
            received.append((args,kwargs))
            return {"id":"order-one"}
        m=SimpleNamespace(market_sell_qty=sell)
        t.install_v19011_sell_telemetry(FakeApp(),m)
        result=m.market_sell_qty("AAPL",2,entry=100,price=99,reason="TEST")
        self.assertEqual(result,{"id":"order-one"})
        self.assertEqual(received,[ (("AAPL",2),{"entry":100,"price":99,"reason":"TEST"}) ])
        self.assertEqual(t._events[-1]["outcome"],"returned")
        self.assertFalse(t._events[-1]["brokerFillVerified"])
    def test_preserves_exception(self):
        def sell(*args,**kwargs): raise ValueError("failed")
        m=SimpleNamespace(market_sell_qty=sell)
        t.install_v19011_sell_telemetry(FakeApp(),m)
        with self.assertRaises(ValueError):
            m.market_sell_qty("AAPL",1,reason="TEST")
        self.assertEqual(t._events[-1]["exceptionType"],"ValueError")

if __name__=="__main__":unittest.main()
