from types import SimpleNamespace
import sys
from types import ModuleType
from backend.v19_crypto_asset_discovery import discover_tradable_usd_crypto

def test_dynamic_all_active_tradable_usd_only(monkeypatch):
    for name in ("alpaca","alpaca.trading","alpaca.trading.requests","alpaca.trading.enums"):
        monkeypatch.setitem(sys.modules,name,ModuleType(name))
    class Request:
        def __init__(self,**kw): self.__dict__.update(kw)
    sys.modules["alpaca.trading.requests"].GetAssetsRequest=Request
    sys.modules["alpaca.trading.enums"].AssetClass=SimpleNamespace(CRYPTO="crypto")
    sys.modules["alpaca.trading.enums"].AssetStatus=SimpleNamespace(ACTIVE="active")
    def asset(symbol, tradable=True, status="active", asset_class="crypto"):
        return SimpleNamespace(symbol=symbol,tradable=tradable,status=status,asset_class=asset_class)
    class Client:
        def get_all_assets(self,query):
            assert query.asset_class=="crypto"
            assert query.status=="active"
            return [asset("UNI/USD"),asset("ETH/USD"),asset("SOL/USD"),
                    asset("XRP/USD"),asset("BTC/USD"),asset("ABC/EUR"),
                    asset("OLD/USD",status="inactive"),
                    asset("NO/USD",tradable=False),
                    asset("AAPL",asset_class="us_equity")]
    assert discover_tradable_usd_crypto(Client())==["BTCUSD","ETHUSD","SOLUSD","UNIUSD","XRPUSD"]

def test_missing_broker_inventory_fails_closed(monkeypatch):
    for name in ("alpaca","alpaca.trading","alpaca.trading.requests","alpaca.trading.enums"):
        monkeypatch.setitem(sys.modules,name,ModuleType(name))
    sys.modules["alpaca.trading.requests"].GetAssetsRequest=lambda **kw: kw
    sys.modules["alpaca.trading.enums"].AssetClass=SimpleNamespace(CRYPTO="crypto")
    sys.modules["alpaca.trading.enums"].AssetStatus=SimpleNamespace(ACTIVE="active")
    class Client:
        def get_all_assets(self,query): return None
    import pytest
    with pytest.raises(ValueError): discover_tradable_usd_crypto(Client())
