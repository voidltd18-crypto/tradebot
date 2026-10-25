from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from backend.v19_xrp_repeat_cycle_snapshot import _filled_sell, xrp_cycle_preview


def filled(*, symbol="XRP/USD", side="sell", status="filled", price="1.32"):
    return SimpleNamespace(symbol=symbol, side=side, status=status,
                           filled_avg_price=price,
                           filled_at=datetime.now(timezone.utc)-timedelta(hours=1))


def test_selects_latest_confirmed_xrp_sell_only():
    orders = [filled(symbol="BTC/USD"), filled(status="canceled"),
              filled(side="buy"), filled()]
    assert _filled_sell(orders)[1] == "1.32"
    assert _filled_sell(orders[:-1]) is None


def test_no_spend_limit_means_no_broker_calls():
    class NoBroker:
        def __getattr__(self, name):
            raise AssertionError("no access should occur")
    out = xrp_cycle_preview(NoBroker(), NoBroker())
    assert out["canEnter"] is False
    assert out["readOnly"] is True


def test_broker_errors_fail_closed():
    class Offline:
        def get_all_positions(self):
            raise ConnectionError("offline")
    assert not xrp_cycle_preview(Offline(), None, spend_usd="25")["canEnter"]
