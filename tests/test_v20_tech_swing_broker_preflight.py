from datetime import datetime, timezone, timedelta
from backend.v20_tech_swing_broker_preflight import inspect_candidate


def check(**overrides):
    now=datetime(2026,11,18,15,tzinfo=timezone.utc)
    args=dict(symbol="AAPL",account={"status":"ACTIVE","trading_blocked":False,"account_blocked":False,"equity":"10000","buying_power":"5000"},
              asset={"symbol":"AAPL","asset_class":"us_equity","tradable":True,"fractionable":True},
              clock={"is_open":True},positions=[],open_orders=[],notional="2500",
              signal_at=now-timedelta(minutes=5),now=now,buys_paused=False,explicit_review=True)
    args.update(overrides)
    return inspect_candidate(**args)


def test_good_preflight_never_authorizes_orders():
    result=check()
    assert result["preflightChecksPassed"]
    assert not result["liveOrdersAuthorized"]
    assert result["ordersSubmitted"]==0


def test_blockers_fail_closed():
    assert "stock_buys_paused" in check(buys_paused=True)["reasons"]
    assert "human_review_missing" in check(explicit_review=False)["reasons"]
    assert "market_not_open" in check(clock={"is_open":False})["reasons"]
    assert "open_order_blocks_new_entry" in check(open_orders=[{"symbol":"AAPL"}])["reasons"]
    assert "existing_position_blocks_new_tech_entry" in check(positions=[{"symbol":"MSFT"}])["reasons"]
    assert "allocation_or_buying_power_limit" in check(notional="2501")["reasons"]
    assert "stale_or_invalid_signal" in check(signal_at=datetime(2026,11,16,tzinfo=timezone.utc))["reasons"]
    assert "symbol_not_in_tech_universe" in check(symbol="MARA")["reasons"]
