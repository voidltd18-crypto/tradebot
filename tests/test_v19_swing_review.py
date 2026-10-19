from datetime import date
import pytest

from backend.v19_swing_review import trading_session_number, swing_review_due


def d(day):
    return date.fromisoformat(day)


def test_entry_session_counts_as_day_one():
    sessions = list(map(d, ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26"]))
    assert trading_session_number(d("2026-10-19"), d("2026-10-19"), sessions) == 1
    assert not swing_review_due(d("2026-10-19"), d("2026-10-22"), sessions)
    assert swing_review_due(d("2026-10-19"), d("2026-10-23"), sessions)
    assert swing_review_due(d("2026-10-19"), d("2026-10-25"), sessions)


def test_weekend_and_market_holiday_excluded():
    sessions = list(map(d, ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27", "2026-11-30", "2026-12-01"]))
    assert trading_session_number(d("2026-11-23"), d("2026-11-26"), sessions) == 3
    assert not swing_review_due(d("2026-11-23"), d("2026-11-27"), sessions)
    assert swing_review_due(d("2026-11-23"), d("2026-11-30"), sessions)


def test_missing_calendar_coverage_fails_closed():
    sessions = [d("2026-10-19"), d("2026-10-20")]
    with pytest.raises(ValueError):
        swing_review_due(d("2026-10-19"), d("2026-10-23"), sessions)


def test_reject_unsorted_or_duplicate_sessions():
    with pytest.raises(ValueError):
        trading_session_number(d("2026-10-19"), d("2026-10-19"), [d("2026-10-20"), d("2026-10-19")])
    with pytest.raises(ValueError):
        trading_session_number(d("2026-10-19"), d("2026-10-19"), [d("2026-10-19"), d("2026-10-19")])


def test_alpaca_calendar_adapter_excludes_holiday():
    from types import SimpleNamespace
    from backend.v19_swing_review import alpaca_trading_sessions

    def fake_calendar(request):
        assert request.start == d("2026-11-23")
        assert request.end == d("2026-11-30")
        return [SimpleNamespace(date=x) for x in [
            d("2026-11-23"), d("2026-11-24"), d("2026-11-25"),
            d("2026-11-27"), d("2026-11-30")
        ]]

    sessions = alpaca_trading_sessions(fake_calendar, d("2026-11-23"), d("2026-11-30"))
    assert d("2026-11-26") not in sessions
    assert swing_review_due(d("2026-11-23"), d("2026-11-30"), sessions)


def test_alpaca_calendar_failure_never_falls_back_to_weekdays():
    from backend.v19_swing_review import alpaca_trading_sessions

    def unavailable(_request):
        return None

    with pytest.raises(ValueError):
        alpaca_trading_sessions(unavailable, d("2026-10-19"), d("2026-10-26"))


def test_review_is_never_an_order_instruction():
    from backend.v19_swing_review import swing_review_snapshot
    sessions = list(map(d, ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]))
    early = swing_review_snapshot(d("2026-10-19"), d("2026-10-22"), sessions)
    due = swing_review_snapshot(d("2026-10-19"), d("2026-10-23"), sessions)
    assert early["action"] == "HOLD_WINDOW"
    assert due["action"] == "REVIEW_ONLY"
    assert due["reviewDue"] is True
    assert "sell" not in due and "order" not in due


def test_entry_date_uses_new_york_exchange_timezone():
    from backend.v19_swing_review import entry_session_from_fill
    assert entry_session_from_fill("2026-10-20T00:15:00Z") == d("2026-10-19")
    assert entry_session_from_fill("2026-10-20T14:00:00+00:00") == d("2026-10-20")


def test_entry_date_rejects_naive_timestamp():
    from backend.v19_swing_review import entry_session_from_fill
    with pytest.raises(ValueError):
        entry_session_from_fill("2026-10-19T14:00:00")


def test_reentry_uses_new_opening_fill():
    from types import SimpleNamespace
    from backend.v19_swing_review import current_position_entry_fill, entry_session_from_fill

    def fill(day, side, qty):
        return SimpleNamespace(symbol="MARA", status="filled", side=side, filled_qty=str(qty), filled_at=day)

    orders = [
        fill("2026-10-12T14:00:00+00:00", "buy", 2),
        fill("2026-10-13T14:00:00+00:00", "sell", 2),
        fill("2026-10-19T14:00:00+00:00", "buy", 1),
        fill("2026-10-20T14:00:00+00:00", "buy", 1),
        fill("2026-10-21T14:00:00+00:00", "sell", 0.5),
    ]
    assert entry_session_from_fill(current_position_entry_fill(orders, "MARA", 1.5)) == d("2026-10-19")


def test_missing_fills_fail_closed():
    from types import SimpleNamespace
    from backend.v19_swing_review import current_position_entry_fill

    incomplete = [SimpleNamespace(symbol="MARA", status="filled", side="buy", filled_qty="1", filled_at="2026-10-19T14:00:00Z")]
    with pytest.raises(ValueError):
        current_position_entry_fill(incomplete, "MARA", 2)
    with pytest.raises(ValueError):
        current_position_entry_fill(incomplete, "MARA", 0.5)
