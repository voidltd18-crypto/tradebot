import sys
import types
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from backend.v19_crypto_profit_sell_executor import poll_profit_sells


def setup_alpaca(monkeypatch):
    req=types.ModuleType("alpaca.trading.requests")
    enum=types.ModuleType("alpaca.trading.enums")
    dreq=types.ModuleType("alpaca.data.requests")
    class Request:
        def __init__(self, **kwargs):
            self.kwargs=kwargs
    req.GetOrdersRequest=Request
    req.LimitOrderRequest=Request
    dreq.CryptoLatestQuoteRequest=Request
    enum.QueryOrderStatus=SimpleNamespace(OPEN="open")
    enum.OrderSide=SimpleNamespace(SELL="sell")
    enum.TimeInForce=SimpleNamespace(GTC="gtc")
    for name, mod in (("alpaca",types.ModuleType("alpaca")),
                      ("alpaca.trading",types.ModuleType("alpaca.trading")),
                      ("alpaca.trading.requests",req),
                      ("alpaca.trading.enums",enum),
                      ("alpaca.data",types.ModuleType("alpaca.data")),
                      ("alpaca.data.requests",dreq)):
        monkeypatch.setitem(sys.modules,name,mod)


class Broker:
    def __init__(self, open_orders=()):
        self.submitted=[]
        self.open_orders=open_orders
    def get_all_positions(self):
        return [SimpleNamespace(symbol="BTCUSD",asset_class="crypto",
                                qty="0.004",avg_entry_price="100")]
    def get_orders(self,filter):
        return self.open_orders
    def submit_order(self,request):
        self.submitted.append(request.kwargs)
        return SimpleNamespace(id="order-id")


class Data:
    def __init__(self,price="104",stale=False):
        self.price=price
        self.stale=stale
    def get_crypto_latest_quote(self,request):
        stamp=datetime.now(timezone.utc)-timedelta(minutes=2) if self.stale else datetime.now(timezone.utc)
        return {"BTC/USD":SimpleNamespace(bid_price=self.price,timestamp=stamp)}


def test_one_limit_sell_and_no_duplicate_after_restart(monkeypatch,tmp_path):
    setup_alpaca(monkeypatch)
    broker=Broker()
    path=str(tmp_path/"test.sqlite")
    first=poll_profit_sells(broker,Data(),path,enabled=True,allowed_symbols=("BTCUSD",))
    again=poll_profit_sells(broker,Data(),path,enabled=True,allowed_symbols=("BTCUSD",))
    assert first["submitted"] == ["BTCUSD"]
    assert not again["submitted"]
    assert len(broker.submitted)==1
    assert broker.submitted[0]["side"] == "sell"
    assert broker.submitted[0]["limit_price"] >= 102


def test_open_order_blocks(monkeypatch,tmp_path):
    setup_alpaca(monkeypatch)
    broker=Broker(open_orders=[SimpleNamespace(symbol="BTC/USD")])
    out=poll_profit_sells(broker,Data(),str(tmp_path/"db"),enabled=True,allowed_symbols=("BTCUSD",))
    assert not out["submitted"]
    assert not broker.submitted


def test_stale_quote_never_places_sell(monkeypatch,tmp_path):
    setup_alpaca(monkeypatch)
    broker=Broker()
    out=poll_profit_sells(broker,Data(stale=True),str(tmp_path/"db"),enabled=True,allowed_symbols=("BTCUSD",))
    assert not out["submitted"]
    assert not broker.submitted


def test_only_opted_in_symbols(monkeypatch,tmp_path):
    setup_alpaca(monkeypatch)
    broker=Broker()
    out=poll_profit_sells(broker,Data(),str(tmp_path/"db"),enabled=True,allowed_symbols=("XRPUSD",))
    assert not out["submitted"]
    assert not broker.submitted
