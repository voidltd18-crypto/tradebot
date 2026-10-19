"""Five-session swing review calculations. No trading or broker side effects.

Entry session counts as day one. Pass actual exchange trading dates to
exclude weekends and market holidays; do not substitute weekday arithmetic.
"""
from datetime import date


def trading_session_number(entry_date: date, as_of: date, sessions: list[date]) -> int:
    """Return 0 before entry, otherwise the inclusive number of sessions elapsed.

    sessions must be an exchange calendar covering the entire period, sorted,
    unique and including the entry session. Missing coverage fails closed.
    """
    if not sessions or sessions != sorted(set(sessions)):
        raise ValueError("sessions must be sorted and unique")
    if entry_date not in sessions:
        raise ValueError("entry session missing from exchange calendar")
    if as_of < entry_date:
        return 0
    if as_of > sessions[-1]:
        raise ValueError("exchange calendar does not cover review date")
    return sum(entry_date <= day <= as_of for day in sessions)


def swing_review_due(entry_date: date, as_of: date, sessions: list[date], max_sessions: int = 5) -> bool:
    """A review flag only; never submits an order or forces an exit."""
    if max_sessions < 1:
        raise ValueError("max_sessions must be positive")
    return trading_session_number(entry_date, as_of, sessions) >= max_sessions
