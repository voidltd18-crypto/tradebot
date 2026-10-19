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


def alpaca_trading_sessions(get_calendar, start: date, end: date) -> list[date]:
    """Fetch exchange sessions from a supplied Alpaca calendar method.

    Caller supplies TradingClient.get_calendar; this module never constructs
    a client, accesses credentials, or submits trades. No weekday fallback.
    """
    if end < start:
        raise ValueError("calendar end precedes start")
    from alpaca.trading.requests import GetCalendarRequest

    rows = get_calendar(GetCalendarRequest(start=start, end=end))
    if rows is None:
        raise ValueError("Alpaca returned no calendar")
    sessions = []
    for row in rows:
        day = row.date
        if isinstance(day, str):
            day = date.fromisoformat(day)
        if not isinstance(day, date):
            raise ValueError("unexpected Alpaca calendar date")
        if not start <= day <= end:
            raise ValueError("Alpaca calendar returned an out-of-range session")
        sessions.append(day)
    if not sessions or sessions != sorted(set(sessions)):
        raise ValueError("Alpaca calendar is empty, unsorted or duplicated")
    return sessions


def swing_review_snapshot(entry_date: date, as_of: date, sessions: list[date], max_sessions: int = 5) -> dict:
    """Read-only status for UI/diagnostics, not a sell signal.

    A due review cannot override emergency stops, hard stops, profit trails,
    broker PDT checks, or entry lockouts. Those remain owned by the trading
    engine and are intentionally not called here.
    """
    day = trading_session_number(entry_date, as_of, sessions)
    if max_sessions < 1:
        raise ValueError("max_sessions must be positive")
    return {
        "holdingTradingDay": day,
        "reviewDue": day >= max_sessions,
        "maxTradingDays": max_sessions,
        "action": "REVIEW_ONLY" if day >= max_sessions else "HOLD_WINDOW",
    }


def entry_session_from_fill(filled_at) -> date:
    """Convert a broker fill timestamp into its New York exchange date.

    Never infer an entry from the current date or from process-local state.
    The caller must first identify the opening fill for the *current* holding,
    including any intervening full close and re-entry.
    """
    from datetime import datetime
    from zoneinfo import ZoneInfo

    if isinstance(filled_at, str):
        filled_at = datetime.fromisoformat(filled_at.replace("Z", "+00:00"))
    if not isinstance(filled_at, datetime) or filled_at.tzinfo is None or filled_at.utcoffset() is None:
        raise ValueError("entry fill requires a timezone-aware timestamp")
    return filled_at.astimezone(ZoneInfo("America/New_York")).date()
