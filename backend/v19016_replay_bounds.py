"""V19.0.16 replay boundary checks; no live trade execution changes."""
from datetime import datetime, timezone

def parse_utc(value):
    if not value:return None
    try:
        dt=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError,TypeError):return None

def bound_replay_to_exit(points,exit_timestamp):
    """Exclude all post-exit prices. Never invent missing pre-exit values."""
    end=parse_utc(exit_timestamp)
    if not end:return [],"EXIT_TIMESTAMP_MISSING"
    kept=[]
    for point in points:
        observed=parse_utc(point.get("point_time"))
        if observed is not None and observed<=end:
            kept.append(point)
    if len(kept)<2:return [],"INSUFFICIENT_PRE_EXIT_POINTS"
    return kept,"BOUNDED_TO_EXIT"
