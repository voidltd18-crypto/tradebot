from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import sys
import types

from backend.v19_crypto_profit_sell_executor import _fresh_quote_or_retry


def _install(monkeypatch):
    module=types.ModuleType("alpaca.data.requests")
    class Req:
        def __init__(self, **kwargs): self.kwargs=kwargs
    module.CryptoLatestQuoteRequest=Req
    monkeypatch.setitem(sys.modules,"alpaca",types.ModuleType("alpaca"))
    monkeypatch.setitem(sys.modules,"alpaca.data",types.ModuleType("alpaca.data"))
    monkeypatch.setitem(sys.modules,"alpaca.data.requests",module)


class Feed:
    def __init__(self,quotes): self.quotes=quotes; self.calls=0
    def get_crypto_latest_quote(self, request):
        index=min(self.calls,len(self.quotes)-1)
        self.calls+=1
        return {"XRP/USD":self.quotes[index]}


def test_retries_stale_and_accepts_verified_fresh(monkeypatch):
    _install(monkeypatch)
    now=datetime.now(timezone.utc)
    feed=Feed([SimpleNamespace(bid_price="1.35",timestamp=now-timedelta(minutes=5)),
               SimpleNamespace(bid_price="1.31",timestamp=now)])
    bid,stamp=_fresh_quote_or_retry(feed,"XRP/USD",requested_at=now)
    assert str(bid)=="1.31"
    assert stamp==now
    assert feed.calls==2


def test_two_stale_quotes_remain_blocked(monkeypatch):
    _install(monkeypatch)
    now=datetime.now(timezone.utc)
    feed=Feed([SimpleNamespace(bid_price="1.35",timestamp=now-timedelta(minutes=5))])
    bid,stamp=_fresh_quote_or_retry(feed,"XRP/USD",requested_at=now)
    assert bid is None and stamp is None
    assert feed.calls==2


def test_future_dated_quote_never_accepted(monkeypatch):
    _install(monkeypatch)
    now=datetime.now(timezone.utc)
    feed=Feed([SimpleNamespace(bid_price="1.35",timestamp=now+timedelta(minutes=1))])
    assert _fresh_quote_or_retry(feed,"XRP/USD",requested_at=now)==(None,None)
