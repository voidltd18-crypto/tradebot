from types import SimpleNamespace
from backend.v19_crypto_profit_sell_executor import _summarize_blocked, _audit_broker_profit_orders


def test_block_reasons_report_known_symbols_only():
    result={"blocked":[("XRPUSD","live bid below target"),
                       ("BTCUSD","open broker order"),
                       ("GOOG","arbitrary text"),
                       ("XRPUSD","private secret with account number")]}
    summary=_summarize_blocked(result)
    assert "XRPUSD=live bid below target" in summary
    assert "BTCUSD=open broker order" in summary
    assert "GOOG" not in summary
    assert "private secret" not in summary


def test_broker_audit_only_counts_confirmed_tradebot_sells(monkeypatch):
    import sys
    import types
    req=types.ModuleType("alpaca.trading.requests")
    enums=types.ModuleType("alpaca.trading.enums")
    class Request:
        def __init__(self,**kwargs): self.kwargs=kwargs
    req.GetOrdersRequest=Request
    enums.QueryOrderStatus=SimpleNamespace(CLOSED="closed")
    for name, mod in (("alpaca",types.ModuleType("alpaca")),
                      ("alpaca.trading",types.ModuleType("alpaca.trading")),
                      ("alpaca.trading.requests",req),("alpaca.trading.enums",enums)):
        monkeypatch.setitem(sys.modules,name,mod)
    class Broker:
        def get_orders(self, filter):
            return [SimpleNamespace(client_order_id="tbprofit-123",status="filled"),
                    SimpleNamespace(client_order_id="tbprofit-456",status="canceled"),
                    SimpleNamespace(client_order_id="other",status="filled")]
    assert _audit_broker_profit_orders(Broker())=={"recentTradeBotClosed":2,"filled":1}
