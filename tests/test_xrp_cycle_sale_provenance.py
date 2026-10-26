from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from backend.v19_xrp_cycle_executor import _is_confirmed_tradebot_profit_sale


def order(**overrides):
    base=dict(symbol="XRP/USD",side="sell",status="filled",
              client_order_id="tbprofit-123", id="order-123",
              filled_avg_price="1.32",
              filled_at=datetime.now(timezone.utc)-timedelta(hours=1))
    return SimpleNamespace(**{**base,**overrides})


def test_only_bot_filled_profit_sale_qualifies():
    assert _is_confirmed_tradebot_profit_sale(order())
    for bad in (dict(client_order_id="manual"),dict(client_order_id=""),
                dict(status="canceled"),dict(status="partially_filled"),
                dict(side="buy"),dict(symbol="BTC/USD"),
                dict(filled_at=None),dict(id=None),dict(filled_avg_price=None)):
        assert not _is_confirmed_tradebot_profit_sale(order(**bad))
