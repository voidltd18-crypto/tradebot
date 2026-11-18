import json
from datetime import date
from backend.v20_tech_swing_research import Bar
from backend.v20_tech_swing_forward_benchmark import BENCHMARK
from backend.v20_tech_swing_forward_report import build_report


def bar(day, p):
    return Bar(date.fromisoformat(day),p,p*1.01,p*.99,p,10000)


def test_combined_report_no_future_and_no_orders(tmp_path):
    path=tmp_path/"candidate-2026-11-17.json"
    path.write_text(json.dumps({"schemaVersion":1,"researchOnly":True,"ordersSubmitted":0,
        "buyEnabled":False,"lastCompletedCommonBar":"2026-11-17",
        "preview":{"topCandidate":"AAPL"}}))
    history={sym:[bar("2026-11-17",100),bar("2026-11-18",100)] for sym in BENCHMARK}
    r=build_report([path],history)
    assert r["observedSignals"]==0
    assert r["benchmarkComparableSignals"]==0
    assert r["ordersSubmitted"]==0
    history={sym:bars+[bar("2026-11-19",110)] for sym,bars in history.items()}
    r=build_report([path],history)
    assert r["observedSignals"]==1
    assert r["benchmarkComparableSignals"]==1
    assert r["meanExcessVsTechPctPoints"]==0
    assert r["forwardSessionsValidated"]==0
