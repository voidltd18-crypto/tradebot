from datetime import datetime, timedelta, timezone
from backend.v19_xrp_repeat_cycle import assess_xrp_dip_entry


def base():
    return dict(ask="1.285", ask_at=datetime.now(timezone.utc),
                positions=[], open_order_symbols=[], available_cash="100",
                spend_usd="10", completed_exit=True)


def test_dip_candidate_without_order_submission():
    result = assess_xrp_dip_entry(**base())
    assert result["canEnter"] is True
    assert result["action"] == "ENTRY_CANDIDATE"
    assert result["readOnly"] is True
    assert result["limitPrice"] == "1.29"


def test_no_duplicate_holdings_or_pending_order():
    for patch in (dict(positions=["XRPUSD"]),
                  dict(open_order_symbols=["XRP/USD"]),
                  dict(completed_exit=False)):
        assert not assess_xrp_dip_entry(**{**base(), **patch})["canEnter"]


def test_no_buy_above_target_or_without_cash():
    for patch in (dict(ask="1.291"), dict(available_cash="9"),
                  dict(spend_usd="0.50"), dict(ask=None)):
        assert not assess_xrp_dip_entry(**{**base(), **patch})["canEnter"]


def test_stale_quote_blocked():
    old = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert not assess_xrp_dip_entry(**{**base(), "ask_at": old})["canEnter"]
