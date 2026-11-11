"""Mocked SDK tests; never connect to Alpaca and never use credentials."""
import sys
from decimal import Decimal
from types import ModuleType, SimpleNamespace
import pytest
from backend.stock_sell_alpaca_paper_adapter import (
    AlpacaPaperStockBroker, make_paper_broker
)


def order(**kwargs):
    return SimpleNamespace(id="order-1", symbol="FMC", side="sell",
                           status="accepted", client_order_id="tb-stock-sell-abc",
                           filled_qty="0", **kwargs)


class APIError(Exception):
    def __init__(self, status_code):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class Client:
    def __init__(self):
        self.position = SimpleNamespace(symbol="FMC", qty="10", side="long")
        self.orders = []
        self.by_client = None
        self.error = None
        self.calls = []
    def get_open_position(self, symbol):
        self.calls.append("position")
        if self.error:
            raise self.error
        return self.position
    def get_orders(self, filter):
        self.calls.append("orders")
        assert filter.symbols == ["FMC"]
        return self.orders
    def get_order_by_client_id(self, cid):
        self.calls.append("lookup")
        if self.error:
            raise self.error
        if self.by_client is None:
            raise APIError(404)
        return self.by_client
    def submit_order(self, request):
        self.calls.append("submit")
        self.last_request = request
        return SimpleNamespace(
            id="order-1", symbol="FMC", side="sell", status="accepted",
            client_order_id=request.client_order_id, filled_qty="0")


@pytest.fixture(autouse=True)
def fake_alpaca(monkeypatch):
    pkg = ModuleType("alpaca")
    trading = ModuleType("alpaca.trading")
    req = ModuleType("alpaca.trading.requests")
    enums = ModuleType("alpaca.trading.enums")
    client_module = ModuleType("alpaca.trading.client")
    req.GetOrdersRequest = lambda **kw: SimpleNamespace(**kw)
    req.MarketOrderRequest = lambda **kw: SimpleNamespace(**kw)
    enums.QueryOrderStatus = SimpleNamespace(OPEN="open")
    enums.OrderSide = SimpleNamespace(SELL="sell")
    enums.TimeInForce = SimpleNamespace(DAY="day")
    recorded = []
    def factory(key, secret, paper=False):
        recorded.append((key, secret, paper))
        return Client()
    client_module.TradingClient = factory
    for name, obj in [
        ("alpaca", pkg), ("alpaca.trading", trading),
        ("alpaca.trading.requests", req), ("alpaca.trading.enums", enums),
        ("alpaca.trading.client", client_module),
    ]:
        monkeypatch.setitem(sys.modules, name, obj)
    yield recorded


def test_factory_rejects_missing_paper_keys():
    with pytest.raises(ValueError):
        make_paper_broker("", "secret")
    with pytest.raises(ValueError):
        make_paper_broker("key", "")


def test_factory_sets_sdk_paper_true(fake_alpaca):
    broker = make_paper_broker("fake", "fake-secret")
    assert fake_alpaca == [("fake", "fake-secret", True)]
    assert broker.fresh_position_qty("FMC") == Decimal("10")


def test_constructor_refuses_unsafe_unverified_client():
    with pytest.raises(ValueError):
        AlpacaPaperStockBroker(Client())


def test_lookup_only_explicit_404_counts_as_absent():
    client = Client()
    broker = AlpacaPaperStockBroker(client, paper_verified=True)
    assert broker.get_order_by_client_id("tb-stock-sell-abc") is None
    client.error = APIError(401)
    with pytest.raises(APIError):
        broker.get_order_by_client_id("tb-stock-sell-abc")
    client.error = APIError(500)
    with pytest.raises(APIError):
        broker.get_order_by_client_id("tb-stock-sell-abc")


def test_open_order_truncation_fails_closed():
    client = Client()
    broker = AlpacaPaperStockBroker(client, paper_verified=True)
    client.orders = [order() for i in range(500)]
    with pytest.raises(ValueError, match="truncated"):
        broker.list_open_orders("FMC")


def test_identity_mismatch_fails_closed():
    client = Client()
    broker = AlpacaPaperStockBroker(client, paper_verified=True)
    client.by_client = SimpleNamespace(
        id="order-1", symbol="FMC", side="sell", status="filled",
        client_order_id="unexpected", filled_qty="10")
    with pytest.raises(ValueError, match="identity"):
        broker.get_order_by_client_id("tb-stock-sell-abc")


def test_submit_is_paper_request_with_deterministic_order_id():
    client = Client()
    broker = AlpacaPaperStockBroker(client, paper_verified=True)
    result = broker.submit_sell(
        "FMC", Decimal("10"), client_order_id="tb-stock-sell-abc")
    assert client.last_request.symbol == "FMC"
    assert client.last_request.side == "sell"
    assert client.last_request.time_in_force == "day"
    assert client.last_request.client_order_id == "tb-stock-sell-abc"
    assert result["id"] == "order-1"
    assert result["side"] == "sell"


def test_short_position_and_non404_missing_position_refused():
    client = Client()
    broker = AlpacaPaperStockBroker(client, paper_verified=True)
    client.position.side = "short"
    with pytest.raises(ValueError, match="short"):
        broker.fresh_position_qty("FMC")
    client.error = APIError(503)
    with pytest.raises(APIError):
        broker.fresh_position_qty("FMC")
    client.error = APIError(404)
    assert broker.fresh_position_qty("FMC") == 0
