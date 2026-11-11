"""Broker adapter contract tests: no real Alpaca calls or orders."""
import sys
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from backend.v19_manual_crypto_rebuy_preview import preview

def test_broker_response_and_recovery(monkeypatch):
    now = datetime.now(timezone.utc)
    class GetOrdersRequest:
        def __init__(self, status, limit): self.status = status
    class CryptoLatestQuoteRequest:
        def __init__(self, symbol_or_symbols): self.symbol = symbol_or_symbols
    class CryptoBarsRequest:
        def __init__(self, **kwargs): self.kwargs = kwargs
    for name in ("alpaca", "alpaca.trading", "alpaca.trading.requests",
                 "alpaca.trading.enums", "alpaca.data", "alpaca.data.requests",
                 "alpaca.data.timeframe"):
        monkeypatch.setitem(sys.modules, name, ModuleType(name))
    sys.modules["alpaca.trading.requests"].GetOrdersRequest = GetOrdersRequest
    sys.modules["alpaca.trading.enums"].QueryOrderStatus = SimpleNamespace(CLOSED="closed", OPEN="open")
    sys.modules["alpaca.data.requests"].CryptoLatestQuoteRequest = CryptoLatestQuoteRequest
    sys.modules["alpaca.data.requests"].CryptoBarsRequest = CryptoBarsRequest
    sys.modules["alpaca.data.timeframe"].TimeFrame = SimpleNamespace(Minute="minute")
    class Broker:
        def get_orders(self, filter):
            if filter.status == "open": return []
            return [SimpleNamespace(symbol="UNI/USD", side="sell", status="filled",
                filled_at=now-timedelta(hours=1), filled_avg_price="100")]
        def get_all_positions(self): return []
    class Data:
        def get_crypto_latest_quote(self, req):
            return {"UNI/USD":SimpleNamespace(timestamp=datetime.now(timezone.utc),ask_price="94")}
        def get_crypto_bars(self, req):
            start = now.replace(second=0,microsecond=0)-timedelta(minutes=15)
            values = [("90","89","91"),("91","90","92"),("92","91","93"),
                      ("92","91","93"),("93","92","94"),("94","93","95"),
                      ("94","93","95"),("95","94","96"),("96","95","97"),
                      ("96","95","97"),("97","96","98"),("98","97","99"),
                      ("98","97","99"),("99","98","100"),("100","99","101")]
            rows = [SimpleNamespace(timestamp=start+timedelta(minutes=i),close=v[0],low=v[1],high=v[2]) for i,v in enumerate(values)]
            return SimpleNamespace(data={"UNI/USD":rows})
    result = preview(Broker(), Data(), "UNIUSD")
    assert result["status"] in ("WATCH","BUY_CANDIDATE")
    assert result["readOnly"] and not result["orderSubmitted"]
    assert result["symbol"] == "UNI/USD"

def test_invalid_pair_never_contacts_broker():
    class Forbidden:
        def __getattr__(self, name): raise AssertionError("Broker called")
    result = preview(Forbidden(), Forbidden(), "UNI/EUR")
    assert result["status"] == "WAIT" and not result["orderSubmitted"]
