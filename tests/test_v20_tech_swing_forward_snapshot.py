from datetime import date, datetime, timedelta, timezone
import pytest
from backend.v20_tech_swing_research import Bar
from backend.v20_tech_swing_forward_snapshot import make_snapshot


def bars():
    start = date(2025, 1, 1)
    return [Bar(start+timedelta(days=i), 100*1.001**i, 101*1.001**i,
                99*1.001**i, 100*1.001**i, 10000) for i in range(300)]


def test_snapshot_uses_prior_day_not_same_day():
    b = bars()
    now = datetime.combine(b[-1].day, datetime.min.time(), tzinfo=timezone.utc)
    result = make_snapshot({"MSFT": b}, recorded_at=now)
    assert result["lastCompletedCommonBar"] == b[-2].day.isoformat()
    assert result["ordersSubmitted"] == 0
    assert result["forwardSessionsValidated"] == 0
    assert not result["buyEnabled"]


def test_stale_data_fails_closed():
    b = bars()
    now = datetime.combine(b[-1].day+timedelta(days=9), datetime.min.time(), tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="Stale"):
        make_snapshot({"MSFT": b}, recorded_at=now)
