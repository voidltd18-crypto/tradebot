from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys
import types

from backend.v19_xrp_cycle_executor import cycle_once
from backend.v19_xrp_repeat_cycle_snapshot import resolve_cycle_spend


def test_all_cash_reserves_fee_headroom():
    assert str(resolve_cycle_spend("100", "ALL")) == "99.00"
    assert str(resolve_cycle_spend("12.34", "ALL")) == "12.21"
    assert resolve_cycle_spend("0.5", "ALL") is None


def setup_api(monkeypatch):
    req = types.ModuleType("alpaca.trading.requests")
    enums = types.ModuleType("alpaca.trading.enums")
    datareq = types.ModuleType("alpaca.data.requests")
    class Req:
        def __init__(self, **kw):
            self.kwargs = kw
    req.GetOrdersRequest = req.LimitOrderRequest = datareq.CryptoLatestQuoteRequest = Req
    enums.QueryOrderStatus = SimpleNamespace(OPEN="open", CLOSED="closed")
    enums.OrderSide = SimpleNamespace(BUY="buy")
    enums.TimeInForce = SimpleNamespace(GTC="gtc")
    for name, module in (
        ("alpaca", types.ModuleType("alpaca")),
        ("alpaca.trading", types.ModuleType("alpaca.trading")),
        ("alpaca.trading.requests", req),
        ("alpaca.trading.enums", enums),
        ("alpaca.data", types.ModuleType("alpaca.data")),
        ("alpaca.data.requests", datareq),
    ):
        monkeypatch.setitem(sys.modules, name, module)


class Broker:
    def __init__(self):
        self.submissions=[]
        self.positions=[]
        self.open_orders=[]
        self.last=datetime.now(timezone.utc)-timedelta(hours=1)
    def get_all_positions(self):
        return self.positions
    def get_orders(self, filter):
        if filter.kwargs["status"] == "open":
            return self.open_orders
        return [SimpleNamespace(id="confirmed-sell-1", client_order_id="tbprofit-confirmed-1", symbol="XRPUSD",
                                side="sell", status="filled",
                                filled_at=self.last, filled_avg_price="1.32")]
    def get_account(self):
        return SimpleNamespace(cash="100",non_marginable_buying_power="100")
    def submit_order(self, request):
        self.submissions.append(request.kwargs)
        return SimpleNamespace(id="accepted")


class Data:
    def get_crypto_latest_quote(self, request):
        return {"XRP/USD":SimpleNamespace(
            ask_price="1.31", timestamp=datetime.now(timezone.utc))}


def test_one_buy_per_filled_sale_and_no_duplicate(monkeypatch,tmp_path):
    setup_api(monkeypatch)
    broker=Broker()
    db=str(tmp_path/"trade.db")
    first=cycle_once(broker,Data(),db,configured_spend="ALL",enabled=True)
    second=cycle_once(broker,Data(),db,configured_spend="ALL",enabled=True)
    assert first["orderSubmitted"] is True
    assert second["orderSubmitted"] is False
    assert len(broker.submissions)==1
    order=broker.submissions[0]
    assert order["side"] == "buy"
    assert order["limit_price"] == 1.3134
    assert order["qty"] * order["limit_price"] <= 99.01


def test_no_buy_while_xrp_held_or_order_open(monkeypatch,tmp_path):
    setup_api(monkeypatch)
    broker=Broker()
    broker.positions=[SimpleNamespace(symbol="XRPUSD")]
    assert not cycle_once(broker,Data(),str(tmp_path/"a.db"),
                          configured_spend="ALL",enabled=True)["orderSubmitted"]
    broker.positions=[]
    broker.open_orders=[SimpleNamespace(symbol="XRP/USD")]
    assert not cycle_once(broker,Data(),str(tmp_path/"b.db"),
                          configured_spend="ALL",enabled=True)["orderSubmitted"]


def test_disabled_never_calls_broker(tmp_path):
    class Exploding:
        def __getattr__(self, key):
            raise AssertionError("called broker")
    assert not cycle_once(Exploding(),Exploding(),str(tmp_path/"a.db"),
                          configured_spend="ALL",enabled=False)["orderSubmitted"]
