import json
from datetime import date
from backend.v20_tech_swing_research import Bar
from backend.v20_tech_swing_forward_outcomes import evaluate_observations


def bar(day, price):
    return Bar(date.fromisoformat(day), price, price*1.01, price*.99, price, 10000)


def test_future_bars_required_and_no_orders(tmp_path):
    p = tmp_path/"s.json"
    p.write_text(json.dumps({"schemaVersion":1,"researchOnly":True,"ordersSubmitted":0,
                            "buyEnabled":False,"lastCompletedCommonBar":"2026-11-17",
                            "preview":{"topCandidate":"AAPL"}}))
    history={"AAPL":[bar("2026-11-17",100),bar("2026-11-18",110)]}
    result=evaluate_observations([p],history)
    assert result["observedSignals"]==0
    assert result["observations"][0]["status"]=="AWAITING_FUTURE_BARS"
    history["AAPL"].append(bar("2026-11-19",121))
    result=evaluate_observations([p],history)
    assert result["observedSignals"]==1
    assert result["observations"][0]["nextSessionOpenToOpenPct"]==10.0
    assert result["forwardSessionsValidated"]==0
    assert result["ordersSubmitted"]==0
