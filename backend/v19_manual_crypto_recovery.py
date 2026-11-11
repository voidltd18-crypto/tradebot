"""Conservative read-only recovery check using completed 5-minute crypto bars."""
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta

def confirmed_recovery(bars, now=None):
    """Require 3 completed rising closes, higher lows and recovery above previous high.
    Fail closed for incomplete, stale or malformed data.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        return False
    try:
        seq = list(bars)
        completed = []
        for bar in seq:
            stamp = bar.timestamp
            if stamp.tzinfo is None:
                return False
            age = (now - stamp).total_seconds()
            # Bar timestamps mark the START of a 5-minute interval.
            if age < 300:
                continue
            if age > 1800:
                continue
            close, low, high = (Decimal(str(getattr(bar, x))) for x in ("close", "low", "high"))
            if not all(v.is_finite() and v > 0 for v in (close, low, high)):
                return False
            if not low <= close <= high:
                return False
            completed.append((stamp, close, low, high))
        completed.sort(key=lambda x: x[0])
        if len(completed) < 3:
            return False
        a, b, c = completed[-3:]
        if not (b[0]-a[0] == timedelta(minutes=5) and c[0]-b[0] == timedelta(minutes=5)):
            return False
        if (now - c[0]).total_seconds() > 660:
            return False
        return a[1] < b[1] < c[1] and a[2] < b[2] < c[2] and c[1] > b[3]
    except (AttributeError, TypeError, ValueError, InvalidOperation):
        return False
