from datetime import date, timedelta
from backend.v20_tech_swing_research import Bar
from backend.v20_tech_swing_candidate_preview import candidate_preview


def bars(growth):
    return [Bar(date(2024,1,1)+timedelta(days=i), 100*(1+growth)**i,
                101*(1+growth)**i, 99*(1+growth)**i,
                100*(1+growth)**i, 10000) for i in range(260)]


def test_top_candidate_read_only():
    result = candidate_preview({"MSFT": bars(.001), "AAPL": bars(.002)})
    assert result["topCandidate"] == "AAPL"
    assert result["ordersSubmitted"] == 0 and not result["buyEnabled"]


def test_historical_cutoff_cannot_use_future_bars():
    result = candidate_preview({"MSFT": bars(.001)}, as_of=date(2024,2,1))
    assert result["topCandidate"] is None
