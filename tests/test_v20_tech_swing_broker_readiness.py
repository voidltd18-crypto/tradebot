from datetime import datetime, timezone
from types import SimpleNamespace
from backend.v20_tech_swing_broker_readiness import broker_readiness


def test_missing_order_inventory_fails_closed():
    class Broker:
        def get_account(self): return SimpleNamespace(status="ACTIVE", trading_blocked=False, account_blocked=False, equity="10000", buying_power="5000")
        def get_asset(self,s): return SimpleNamespace(symbol=s, asset_class="us_equity", tradable=True, fractionable=True)
        def get_clock(self): return SimpleNamespace(is_open=True)
        def get_all_positions(self): return []
        def submit_order(self,*args,**kwargs): raise AssertionError("No orders")
    r=broker_readiness(Broker(),symbol="AAPL",notional=100,
                       signal_at=datetime.now(timezone.utc),buys_paused=False,explicit_review=True)
    assert r["brokerReadVerified"] is False
    assert r["ordersSubmitted"]==0


def test_verified_reads_do_not_authorize_order():
    class Broker:
        def get_account(self): return SimpleNamespace(status="ACTIVE", trading_blocked=False, account_blocked=False, equity="10000", buying_power="5000")
        def get_asset(self,s): return SimpleNamespace(symbol=s, asset_class="us_equity", tradable=True, fractionable=True)
        def get_clock(self): return SimpleNamespace(is_open=True)
        def get_all_positions(self): return []
        def get_open_orders_for_preflight(self): return []
        def submit_order(self,*args,**kwargs): raise AssertionError("No orders")
    r=broker_readiness(Broker(),symbol="AAPL",notional=100,
                       signal_at=datetime.now(timezone.utc),buys_paused=False,explicit_review=True)
    assert r["brokerReadVerified"] is True
    assert r["preflightChecksPassed"] is True
    assert r["liveOrdersAuthorized"] is False
    assert r["ordersSubmitted"]==0


def test_alpaca_open_orders_filter_and_no_submit(monkeypatch):
    import sys
    from types import ModuleType
    parent=ModuleType("alpaca")
    trading=ModuleType("alpaca.trading")
    requests=ModuleType("alpaca.trading.requests")
    enums=ModuleType("alpaca.trading.enums")
    class QueryOrderStatus:
        OPEN="open"
    class GetOrdersRequest:
        def __init__(self, *, status): self.status=status
    requests.GetOrdersRequest=GetOrdersRequest
    enums.QueryOrderStatus=QueryOrderStatus
    for name,module in [("alpaca",parent),("alpaca.trading",trading),
                        ("alpaca.trading.requests",requests),("alpaca.trading.enums",enums)]:
        monkeypatch.setitem(sys.modules,name,module)
    class Broker:
        def get_account(self): return SimpleNamespace(status="ACTIVE", trading_blocked=False, account_blocked=False, equity="10000", buying_power="5000")
        def get_asset(self,s): return SimpleNamespace(symbol=s, asset_class="us_equity", tradable=True, fractionable=True)
        def get_clock(self): return SimpleNamespace(is_open=True)
        def get_all_positions(self): return []
        def get_orders(self, *, filter):
            assert isinstance(filter,GetOrdersRequest)
            assert filter.status=="open"
            return []
        def submit_order(self,*args,**kwargs): raise AssertionError("No orders")
    r=broker_readiness(Broker(),symbol="AAPL",notional=100,
                       signal_at=datetime.now(timezone.utc),buys_paused=False,explicit_review=True)
    assert r["brokerReadVerified"] is True
    assert r["preflightChecksPassed"] is True
    assert r["liveOrdersAuthorized"] is False
