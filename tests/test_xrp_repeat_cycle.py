from datetime import datetime, timedelta, timezone
from decimal import Decimal
from backend.v19_xrp_repeat_cycle import assess_xrp_dip_entry


def case(**changes):
    now = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)
    values = dict(ask="1.312", ask_at=now, positions=[],
                  open_order_symbols=[], available_cash="100", spend_usd="25",
                  last_sale_price="1.32", last_sale_at=now-timedelta(hours=1),
                  last_sale_filled=True, pullback_pct="0.5", now=now)
    return assess_xrp_dip_entry(**{**values, **changes})


def test_dynamic_half_percent_from_confirmed_sale():
    result = case()
    assert result["canEnter"] is True
    assert result["targetAskAtMost"] == "1.31340000"
    assert result["readOnly"] is True
    assert result["action"] == "ENTRY_CANDIDATE"


def test_no_fixed_129_needed():
    assert case(ask="1.31")["canEnter"] is True
    assert case(ask="1.314")["canEnter"] is False
    assert case(last_sale_price="1.50", ask="1.49")["canEnter"] is True


def test_optional_one_percent_pullback():
    assert case(ask="1.31", pullback_pct="1")["canEnter"] is False
    assert case(ask="1.305", pullback_pct="1")["canEnter"] is True


def test_never_buy_while_position_or_order_open():
    assert case(positions=["XRPUSD"])["canEnter"] is False
    assert case(open_order_symbols=["XRP/USD"])["canEnter"] is False


def test_missing_or_unfilled_sale_fails_closed():
    assert case(last_sale_filled=False)["canEnter"] is False
    assert case(last_sale_at=None)["canEnter"] is False
    assert case(last_sale_price=None)["canEnter"] is False


def test_cooldown_quote_age_and_sale_age():
    now = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)
    assert case(last_sale_at=now-timedelta(minutes=5))["canEnter"] is False
    assert case(ask_at=now-timedelta(seconds=50))["canEnter"] is False
    assert case(last_sale_at=now-timedelta(days=8))["canEnter"] is False


def test_cash_and_spend_gate():
    assert case(available_cash="10", spend_usd="25")["canEnter"] is False
    assert case(spend_usd="0")["canEnter"] is False
    assert case(spend_usd=None)["canEnter"] is False


def test_invalid_settings_fail_closed():
    assert case(pullback_pct="0")["canEnter"] is False
    assert case(pullback_pct="3")["canEnter"] is False
    assert case(cooldown_minutes=0)["canEnter"] is False
