from datetime import date
from backend.v20_tech_swing_research import Bar
from backend.v20_tech_swing_forward_benchmark import BENCHMARK, compare_to_tech_basket


def bar(day, price):
    return Bar(date.fromisoformat(day),price,price*1.01,price*.99,price,10000)


def test_equal_basket_and_zero_excess():
    history={sym:[bar("2026-11-18",100),bar("2026-11-19",110)] for sym in BENCHMARK}
    report={"observations":[{"signalDay":"2026-11-17","symbol":"AAPL",
             "status":"OBSERVED","entryDay":"2026-11-18","exitDay":"2026-11-19",
             "nextSessionOpenToOpenPct":10.0}]}
    result=compare_to_tech_basket(report,history)
    assert result["comparableSignals"]==1
    assert result["meanExcessPctPoints"]==0
    assert result["ordersSubmitted"]==0
    assert result["forwardSessionsValidated"]==0


def test_missing_benchmark_not_silently_substituted():
    report={"observations":[{"signalDay":"2026-11-17","symbol":"AAPL",
             "status":"OBSERVED","entryDay":"2026-11-18","exitDay":"2026-11-19",
             "nextSessionOpenToOpenPct":10.0}]}
    result=compare_to_tech_basket(report,{"AAPL":[bar("2026-11-18",100),bar("2026-11-19",110)]})
    assert result["comparableSignals"]==0
    assert result["comparisons"][0]["status"]=="BENCHMARK_MISSING"
