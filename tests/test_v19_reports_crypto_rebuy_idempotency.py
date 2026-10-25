"""Broker-simulated coverage. Never calls a real brokerage account."""
import sys
import types
import uuid
from types import SimpleNamespace
from backend.v19_reports_crypto_rebuy import rebuy_order


class FakeBroker:
    _paper = True
    def __init__(self, fail=False, cash="500"):
        self.calls = []
        self.fail = fail
        self.cash = cash

    def get_asset(self, symbol):
        assert symbol == "XRPUSD"
        return SimpleNamespace(asset_class="crypto", tradable=True)

    def get_account(self):
        return SimpleNamespace(non_marginable_buying_power=self.cash)

    def get_orders(self, filter):
        return []

    def submit_order(self, order):
        self.calls.append(order)
        if self.fail:
            raise TimeoutError("unknown submission result")
        return SimpleNamespace(id="paper-123")


def _mock_alpaca(monkeypatch):
    requests = types.ModuleType("alpaca.trading.requests")
    enums = types.ModuleType("alpaca.trading.enums")
    class Order:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
    requests.MarketOrderRequest = Order
    requests.GetOrdersRequest = Order
    enums.QueryOrderStatus = SimpleNamespace(OPEN="open")
    enums.OrderSide = SimpleNamespace(BUY="buy")
    enums.TimeInForce = SimpleNamespace(GTC="gtc")
    monkeypatch.setitem(sys.modules, "alpaca", types.ModuleType("alpaca"))
    monkeypatch.setitem(sys.modules, "alpaca.trading", types.ModuleType("alpaca.trading"))
    monkeypatch.setitem(sys.modules, "alpaca.trading.requests", requests)
    monkeypatch.setitem(sys.modules, "alpaca.trading.enums", enums)


def _buy(broker, db_path, request_id):
    return rebuy_order(broker, symbol="XRP/USD", amount="25.00",
                       confirmation="BUY XRP/USD", allowed_ids={"XRP/USD"},
                       request_id=request_id, db_path=str(db_path),
                       enabled=True, is_paper=True)


def test_one_broker_submission_for_same_request_even_after_restart(tmp_path, monkeypatch):
    _mock_alpaca(monkeypatch)
    broker = FakeBroker()
    key = str(uuid.uuid4())
    db = tmp_path / "persist.sqlite"
    first = _buy(broker, db, key)
    second = _buy(broker, db, key)
    assert first["orderSubmitted"] is True
    assert second["orderSubmitted"] is False
    assert len(broker.calls) == 1
    assert broker.calls[0].kwargs["client_order_id"] == "tb-rebuy-" + key
    assert broker.calls[0].kwargs["symbol"] == "XRP/USD"


def test_ambiguous_broker_response_is_not_retried(tmp_path, monkeypatch):
    _mock_alpaca(monkeypatch)
    broker = FakeBroker(fail=True)
    key = str(uuid.uuid4())
    db = tmp_path / "persist.sqlite"
    assert not _buy(broker, db, key)["orderSubmitted"]
    broker.fail = False
    assert not _buy(broker, db, key)["orderSubmitted"]
    assert len(broker.calls) == 1


def test_insufficient_cash_and_missing_id_fail_before_order(tmp_path, monkeypatch):
    _mock_alpaca(monkeypatch)
    broker = FakeBroker(cash="2")
    assert not _buy(broker, tmp_path / "db.sqlite", str(uuid.uuid4()))["orderSubmitted"]
    broker.cash = "500"
    assert not _buy(broker, tmp_path / "db.sqlite", "not-a-uuid")["orderSubmitted"]
    assert not broker.calls


def test_live_account_stays_disabled_without_explicit_opt_in(tmp_path, monkeypatch):
    _mock_alpaca(monkeypatch)
    broker = FakeBroker()
    broker._paper = False
    out = rebuy_order(broker, symbol="XRP/USD", amount="25.00",
                      confirmation="BUY XRP/USD", allowed_ids={"XRP/USD"},
                      request_id=str(uuid.uuid4()), db_path=str(tmp_path / "db.sqlite"),
                      enabled=True, is_paper=False, allow_live=False)
    assert not out["orderSubmitted"]
    assert not broker.calls

def test_pending_broker_order_blocks_rebuy(tmp_path, monkeypatch):
    _mock_alpaca(monkeypatch)
    broker = FakeBroker()
    broker.get_orders = lambda filter: [SimpleNamespace(symbol="XRPUSD")]
    out = _buy(broker, tmp_path / "db.sqlite", str(uuid.uuid4()))
    assert not out["orderSubmitted"]
    assert not broker.calls


def test_broker_order_lookup_error_fails_closed(tmp_path, monkeypatch):
    _mock_alpaca(monkeypatch)
    broker = FakeBroker()
    def fail(filter):
        raise ConnectionError("orders unavailable")
    broker.get_orders = fail
    out = _buy(broker, tmp_path / "db.sqlite", str(uuid.uuid4()))
    assert not out["orderSubmitted"]
    assert not broker.calls
