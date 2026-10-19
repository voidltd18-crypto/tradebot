from datetime import date
import pytest

from backend.v19_swing_review import trading_session_number, swing_review_due


def d(day):
    return date.fromisoformat(day)


def test_entry_session_counts_as_day_one():
    sessions = list(map(d, ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"]))
    assert trading_session_number(d("2026-10-19"), d("2026-10-19"), sessions) == 1
    assert not swing_review_due(d("2026-10-19"), d("2026-10-22"), sessions)
    assert swing_review_due(d("2026-10-19"), d("2026-10-23"), sessions)


def test_weekend_and_market_holiday_excluded():
    sessions = list(map(d, ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27", "2026-11-30"]))
    assert trading_session_number(d("2026-11-23"), d("2026-11-26"), sessions) == 3
    assert swing_review_due(d("2026-11-23"), d("2026-11-30"), sessions)


def test_missing_calendar_coverage_fails_closed():
    sessions = [d("2026-10-19"), d("2026-10-20")]
    with pytest.raises(ValueError):
        swing_review_due(d("2026-10-19"), d("2026-10-23"), sessions)
