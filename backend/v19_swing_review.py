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


def current_position_entry_fill(orders, symbol: str, current_qty: float):
    """Reconstruct opening fill for current long holding from complete fills.

    Orders must be complete, chronologically ordered executed fills for this
    symbol, including partial executions. A mismatch with broker position
    quantity fails closed. Never infer a fill from order submission/update.
    """
    from datetime import datetime
    from decimal import Decimal, InvalidOperation

    if not symbol or current_qty <= 0:
        raise ValueError("active symbol and positive quantity required")
    events = []
    for order in orders:
        if str(getattr(order, "symbol", "")).upper() != symbol.upper():
            continue
        status = str(getattr(order, "status", "")).lower()
        # A terminal order with zero executed shares cannot affect position
        # inventory. Partially executed orders still require fill-level history.
        try:
            reported_qty = Decimal(str(getattr(order, "filled_qty", None)))
        except (InvalidOperation, TypeError):
            raise ValueError("invalid filled quantity")
        if not reported_qty.is_finite() or reported_qty < 0:
            raise ValueError("invalid filled quantity")
        terminal_unfilled = {
            "canceled", "cancelled", "expired", "rejected", "replaced",
            "done_for_day", "orderstatus.canceled", "orderstatus.cancelled",
            "orderstatus.expired", "orderstatus.rejected",
            "orderstatus.replaced", "orderstatus.done_for_day",
        }
        if status in terminal_unfilled and reported_qty == 0:
            continue
        if status not in {"filled", "orderstatus.filled"}:
            raise ValueError("non-final or partially executed order requires execution-level fill history")
        stamp = getattr(order, "filled_at", None)
        if stamp is None:
            raise ValueError("missing confirmed fill timestamp")
        if isinstance(stamp, str):
            stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("fill timestamp must be timezone-aware")
        try:
            qty = Decimal(str(getattr(order, "filled_qty", None)))
        except (InvalidOperation, TypeError):
            raise ValueError("invalid filled quantity")
        if not qty.is_finite() or qty <= 0:
            raise ValueError("invalid filled quantity")
        side = str(getattr(order, "side", "")).lower()
        if side in {"orderside.buy", "buy"}:
            sign = 1
        elif side in {"orderside.sell", "sell"}:
            sign = -1
        else:
            raise ValueError("unknown fill side")
        events.append((stamp, sign, qty))
    if not events or events != sorted(events, key=lambda row: row[0]):
        raise ValueError("fill history missing or not chronologically ordered")
    balance = Decimal("0")
    entry = None
    for stamp, sign, qty in events:
        if sign == 1:
            if balance == 0:
                entry = stamp
            balance += qty
        else:
            balance -= qty
            if balance < 0:
                raise ValueError("fill history incomplete or includes short selling")
            if balance == 0:
                entry = None
    if abs(balance - Decimal(str(current_qty))) > Decimal("0.000001") or entry is None:
        raise ValueError("fills do not reconcile to current broker position")
    return entry


def safe_position_swing_review(orders, symbol: str, current_qty: float, as_of: date, sessions: list[date], max_sessions: int = 5) -> dict:
    """Diagnostic-only adapter: unknown data never produces a due-review signal.

    Supply complete confirmed fills for this symbol and a verified exchange
    calendar. This function neither fetches orders nor performs trading.
    """
    try:
        entry_fill = current_position_entry_fill(orders, symbol, current_qty)
        entry_day = entry_session_from_fill(entry_fill)
        snapshot = swing_review_snapshot(entry_day, as_of, sessions, max_sessions)
        return {"symbol": symbol, "entrySession": entry_day.isoformat(), "status": "verified", **snapshot}
    except (ValueError, TypeError, AttributeError, OverflowError) as exc:
        return {
            "symbol": symbol, "entrySession": None, "status": "unverified",
            "holdingTradingDay": None, "reviewDue": False,
            "maxTradingDays": max_sessions, "action": "NO_ACTION",
            "reason": str(exc),
        }


def sideways_review_assessment(review: dict, unrealized_pct: float, flat_band_pct: float = 0.5) -> dict:
    """Diagnostic only. A flat position is a review candidate, never a sell order."""
    from math import isfinite

    if not isinstance(review, dict) or review.get("status") != "verified" or not review.get("reviewDue"):
        return {"status": "not_due_or_unverified", "action": "NO_ACTION"}
    if not isinstance(unrealized_pct, (float, int)) or not isfinite(unrealized_pct):
        return {"status": "unverified", "action": "NO_ACTION"}
    if not isinstance(flat_band_pct, (float, int)) or not isfinite(flat_band_pct) or flat_band_pct < 0:
        raise ValueError("flat band must be finite and nonnegative")
    if abs(unrealized_pct) <= flat_band_pct:
        return {"status": "sideways", "action": "CONSIDER_ROTATION"}
    return {"status": "moving", "action": "REVIEW_ONLY"}


def execution_activities_as_fills(activities: list[dict]) -> list:
    """Adapt broker FILL executions (including partials) for reconciliation.

    Each activity is an incremental execution, not cumulative order quantity.
    Reject missing IDs, duplicate activities and invalid records. Read-only.
    """
    from datetime import datetime
    from decimal import Decimal, InvalidOperation
    from types import SimpleNamespace

    seen = set()
    events = []
    for activity in activities:
        if not isinstance(activity, dict) or str(activity.get("activity_type", "")).upper() != "FILL":
            raise ValueError("non-fill activity in execution history")
        activity_id = str(activity.get("id") or "")
        symbol = str(activity.get("symbol") or "").upper()
        side = str(activity.get("side") or "").lower()
        stamp = activity.get("transaction_time")
        if not activity_id or activity_id in seen or not symbol or side not in {"buy", "sell"}:
            raise ValueError("missing or duplicate fill activity details")
        seen.add(activity_id)
        try:
            qty = Decimal(str(activity.get("qty")))
            dt = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("invalid execution quantity or timestamp")
        if not qty.is_finite() or qty <= 0 or dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("invalid execution quantity or timestamp")
        events.append((dt, activity_id, SimpleNamespace(
            symbol=symbol, side=side, status="filled",
            filled_qty=str(qty), filled_at=dt,
        )))
    events.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in events]
