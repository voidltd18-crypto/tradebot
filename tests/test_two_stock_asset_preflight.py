"""No live application import; mock Alpaca asset responses only."""
from pathlib import Path
from types import SimpleNamespace

from backend.v19_two_stock_asset_preflight import check_asset, check_from_broker

def asset(symbol, name, **values):
    base = dict(symbol=symbol, name=name, asset_class="us_equity", status="active",
                tradable=True, fractionable=True)
    base.update(values)
    return SimpleNamespace(**base)

def test_accepts_valid_tesla_and_spacex_assets():
    assert check_asset("TSLA", asset("TSLA", "Tesla, Inc. Common Stock"))["eligible"]
    assert check_asset("SPCX", asset("SPCX", "Space Exploration Technologies Corp. Class A"))["eligible"]

def test_rejects_old_spcx_etf_identity():
    p = check_asset("SPCX", asset("SPCX", "The SPAC and New Issue ETF"))
    assert not p["eligible"]
    assert "issuer_identity_unverified" in p["reasons"]

def test_rejects_inactive_nontradable_nonfractional_assets():
    p = check_asset("SPCX", asset("SPCX", "SpaceX", status="inactive",
                                  tradable=False, fractionable=False))
    assert not p["eligible"]
    assert set(p["reasons"]) >= {"asset_inactive", "not_tradable",
                                 "not_fractionable_for_notional_order"}

def test_rejects_symbol_mismatch_and_other_asset_classes():
    p = check_asset("SPCX", asset("SPCK", "SpaceX", asset_class="crypto"))
    assert "ticker_mismatch" in p["reasons"]
    assert "not_us_equity" in p["reasons"]

def test_rejects_missing_identity_and_missing_broker_reply():
    assert not check_asset("SPCX", None)["eligible"]

    class FailedBroker:
        def get_asset(self, symbol):
            raise RuntimeError("Alpaca service unavailable")

    assert check_from_broker(FailedBroker(), "SPCX")["reasons"] == ["broker_asset_lookup_failed"]

def test_live_broker_lookup_never_places_order():
    class MockBroker:
        def __init__(self):
            self.calls = []
        def get_asset(self, symbol):
            self.calls.append(("get_asset", symbol))
            return asset(symbol, "Tesla Inc" if symbol == "TSLA" else "SpaceX")
        def submit_order(self, *args, **kwargs):
            raise AssertionError("preflight must never order")

    broker = MockBroker()
    assert check_from_broker(broker, "TSLA")["eligible"]
    assert check_from_broker(broker, "SPCX")["eligible"]
    assert broker.calls == [("get_asset", "TSLA"), ("get_asset", "SPCX")]

def test_market_buy_path_fail_closed_and_opt_in_mode_off():
    src = Path("backend/legacy/monolith.py").read_text()
    assert 'TRADEBOT_TWO_STOCK_MODE", "true"' in src
    assert 'TRADEBOT_STOCK_BUYS_PAUSED", "true"' in src
    assert "broker_asset = check_from_broker(trading_client, symbol)" in src
    assert 'if not broker_asset["eligible"]:' in src
    assert "MARA_DAILY_ENTRY_LIMIT = 1" in src
