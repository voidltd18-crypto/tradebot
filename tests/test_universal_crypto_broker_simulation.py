"""Offline broker simulation for universal crypto re-buy: no real orders."""
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
import sys

from backend.v19_universal_crypto_cycle_executor import cycle_once

NOW = datetime.now(timezone.utc)

def _install_fake_alpaca(monkeypatch):
    # Mock imported Alpaca request/enums so this runs without broker credentials.
    for name in ("alpaca", "alpaca.trading", "alpaca.trading.requests",
                 "alpaca.trading.enums", "alpaca.data", "alpaca.data.requests"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    requests = sys.modules["alpaca.trading.requests"]
    enums = sys.modules["alpaca.trading.enums"]
    data_requests = sys.modules["alpaca.data.requests"]
    class Request:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    requests.GetOrdersRequest = Request
    requests.LimitOrderRequest = Request
    data_requests.CryptoLatestQuoteRequest = Request
    enums.QueryOrderStatus = SimpleNamespace(OPEN="open", CLOSED="closed")
    enums.OrderSide = SimpleNamespace(BUY="buy")
    enums.TimeInForce = SimpleNamespace(GTC="gtc")

def test_profit_sell_then_dip_rebuy_once(monkeypatch, tmp_path):
    _install_fake_alpaca(monkeypatch)
    sale = SimpleNamespace(symbol="UNIUSD", side="sell", status="filled",
        client_order_id="tbprofit-original", filled_at=NOW-timedelta(minutes=31),
        filled_avg_price="7.00", id="sale_1")
    class Broker:
        orders = []
        def get_all_positions(self): return []
        def get_orders(self, filter):
            return [sale] if filter.status == "closed" else []
        def get_account(self): return SimpleNamespace(cash="200", buying_power="200")
        def submit_order(self, order):
            self.orders.append(order)
            return SimpleNamespace(id="order_1")
    class Quotes:
        def get_crypto_latest_quote(self, request):
            return {"UNI/USD": SimpleNamespace(ask_price="6.95", timestamp=datetime.now(timezone.utc))}
    broker=Broker()
    # isolate available cash formula to avoid depending on unrelated broker model
    import backend.v19_universal_crypto_cycle_executor as module
    monkeypatch.setattr(module, "available_crypto_cash", lambda account: 200)
    first=cycle_once(broker,Quotes(),str(tmp_path/"cycles.sqlite"),symbol="UNIUSD",
                     configured_spend="100",enabled=True)
    assert first["orderSubmitted"]
    assert len(broker.orders)==1
    assert broker.orders[0].time_in_force=="gtc"
    assert broker.orders[0].side=="buy"
    assert broker.orders[0].symbol=="UNI/USD"
    second=cycle_once(broker,Quotes(),str(tmp_path/"cycles.sqlite"),symbol="UNIUSD",
                      configured_spend="100",enabled=True)
    assert not second["orderSubmitted"]
    assert len(broker.orders)==1

def test_holding_other_crypto_fails_closed(monkeypatch, tmp_path):
    _install_fake_alpaca(monkeypatch)
    class Broker:
        def get_all_positions(self):
            return [SimpleNamespace(symbol="BTCUSD",asset_class="crypto")]
        def submit_order(self, order):
            raise AssertionError("must not place order")
    result=cycle_once(Broker(),object(),str(tmp_path/"guard.sqlite"),
                      symbol="UNIUSD",configured_spend="100",enabled=True)
    assert not result["orderSubmitted"]
    assert "another crypto position" in result["status"]
