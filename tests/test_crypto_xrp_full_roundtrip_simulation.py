"""Simulation: qualifying XRP limit SELL -> confirmed fill -> cooled-down dip BUY.

No live broker, no environment activation. CI-only end-to-end guard.
"""
import sys
import types
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.v19_crypto_profit_sell_executor import poll_profit_sells
from backend.v19_xrp_cycle_executor import cycle_once


def _modules(monkeypatch):
    req=types.ModuleType("alpaca.trading.requests")
    enums=types.ModuleType("alpaca.trading.enums")
    quotes=types.ModuleType("alpaca.data.requests")
    class Request:
        def __init__(self, **kw):
            self.kwargs=kw
    req.GetOrdersRequest=Request
    req.LimitOrderRequest=Request
    quotes.CryptoLatestQuoteRequest=Request
    enums.QueryOrderStatus=SimpleNamespace(OPEN="open", CLOSED="closed")
    enums.OrderSide=SimpleNamespace(SELL="sell", BUY="buy")
    enums.TimeInForce=SimpleNamespace(GTC="gtc")
    for name,mod in [
        ("alpaca",types.ModuleType("alpaca")),
        ("alpaca.trading",types.ModuleType("alpaca.trading")),
        ("alpaca.trading.requests",req),
        ("alpaca.trading.enums",enums),
        ("alpaca.data",types.ModuleType("alpaca.data")),
        ("alpaca.data.requests",quotes),
    ]:
        monkeypatch.setitem(sys.modules,name,mod)


class Broker:
    def __init__(self):
        self.positions=[SimpleNamespace(symbol="XRPUSD",asset_class="crypto",
                                        qty="100",avg_entry_price="1.30")]
        self.open=[]
        self.closed=[]
        self.orders=[]
    def get_all_positions(self):
        return list(self.positions)
    def get_orders(self,filter):
        return list(self.open if filter.kwargs["status"]=="open" else self.closed)
    def get_account(self):
        return SimpleNamespace(cash="100",non_marginable_buying_power="100")
    def submit_order(self,request):
        self.orders.append(request.kwargs)
        return SimpleNamespace(id="mock-order")


class Data:
    def __init__(self, bid, ask, stamp):
        self.bid=bid
        self.ask=ask
        self.stamp=stamp
    def get_crypto_latest_quote(self,request):
        return {"XRP/USD":SimpleNamespace(
            bid_price=self.bid,ask_price=self.ask,timestamp=self.stamp)}


def test_full_xrp_profit_sale_then_dynamic_reentry(monkeypatch,tmp_path):
    _modules(monkeypatch)
    broker=Broker()
    t=datetime.now(timezone.utc)
    db=str(tmp_path/"cycle.sqlite")
    sell=poll_profit_sells(
        broker,Data(bid="1.32",ask="1.321",stamp=t),db,
        now=t,enabled=True,allowed_symbols=("XRPUSD",),
        min_gain_pct="1",cost_buffer_pct="0.75")
    assert sell["submitted"]==["XRPUSD"]
    assert len(broker.orders)==1
    assert broker.orders[0]["side"]=="sell"
    assert broker.orders[0]["limit_price"] >= 1.313
    # Open sell order blocks any subsequent buy.
    broker.open=[SimpleNamespace(symbol="XRP/USD")]
    blocked=cycle_once(
        broker,Data("1.305","1.31",t),db,
        enabled=True,configured_spend="ALL",now=t)
    assert blocked["orderSubmitted"] is False
    # Broker confirms fill; holding disappears, cooldown begins.
    broker.open=[]
    broker.positions=[]
    broker.closed=[SimpleNamespace(
        id="sale-confirmed-001",client_order_id="tbprofit-example",
        symbol="XRP/USD",side="sell",status="filled",
        filled_at=t,filled_avg_price="1.32")]
    too_soon=cycle_once(broker,Data("1.305","1.31",t),db,
                         enabled=True,configured_spend="ALL",now=t)
    assert too_soon["orderSubmitted"] is False
    # Price stays below the 0.5% pullback target after 31 minutes.
    later=t+timedelta(minutes=31)
    reentry=cycle_once(broker,Data("1.305","1.31",later),db,
                        enabled=True,configured_spend="ALL",now=later)
    assert reentry["orderSubmitted"] is True
    assert len(broker.orders)==2
    buy=broker.orders[-1]
    assert buy["side"]=="buy"
    assert buy["limit_price"] <= 1.3134
    assert buy["qty"]*buy["limit_price"] <= 99.01
    # A second worker run must not buy again for the same confirmed sale.
    repeated=cycle_once(broker,Data("1.305","1.31",later),db,
                        enabled=True,configured_spend="ALL",now=later)
    assert repeated["orderSubmitted"] is False
    assert len(broker.orders)==2


def test_no_cycle_when_broker_sale_never_filled(monkeypatch,tmp_path):
    _modules(monkeypatch)
    broker=Broker()
    broker.positions=[]
    broker.closed=[SimpleNamespace(id="unsuccessful",symbol="XRP/USD",
                                    side="sell",status="canceled",
                                    filled_at=datetime.now(timezone.utc)-timedelta(hours=1),
                                    filled_avg_price="1.32")]
    t=datetime.now(timezone.utc)
    result=cycle_once(broker,Data("1.30","1.31",t),
                      str(tmp_path/"db.sqlite"),enabled=True,
                      configured_spend="ALL",now=t)
    assert result["orderSubmitted"] is False
    assert broker.orders==[]
