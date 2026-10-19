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
