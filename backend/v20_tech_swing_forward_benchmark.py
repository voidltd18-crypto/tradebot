"""Compare observed signal returns against date-aligned equal-weight tech returns."""
from __future__ import annotations

BENCHMARK = ("AAPL", "AMZN", "GOOGL", "META", "MSFT", "NVDA")


def compare_to_tech_basket(observation_report, history):
    indexed = {sym: {bar.day.isoformat(): bar for bar in bars}
               for sym, bars in history.items()}
    comparisons = []
    for row in observation_report["observations"]:
        if row["status"] != "OBSERVED":
            continue
        start, end = row["entryDay"], row["exitDay"]
        if any(start not in indexed.get(sym, {}) or end not in indexed.get(sym, {})
               for sym in BENCHMARK):
            comparisons.append({"signalDay": row["signalDay"], "status": "BENCHMARK_MISSING"})
            continue
        returns = [100 * (indexed[sym][end].open / indexed[sym][start].open - 1)
                   for sym in BENCHMARK]
        baseline = sum(returns) / len(returns)
        comparisons.append({"signalDay": row["signalDay"], "status": "COMPARED",
                            "symbol": row["symbol"],
                            "candidateReturnPct": row["nextSessionOpenToOpenPct"],
                            "equalWeightTechReturnPct": round(baseline, 4),
                            "excessPctPoints": round(row["nextSessionOpenToOpenPct"]-baseline, 4)})
    comparable = [row for row in comparisons if row["status"] == "COMPARED"]
    return {"researchOnly": True, "ordersSubmitted": 0, "buyEnabled": False,
            "forwardSessionsValidated": 0, "comparableSignals": len(comparable),
            "meanExcessPctPoints": round(sum(row["excessPctPoints"] for row in comparable) / len(comparable), 4) if comparable else None,
            "comparisons": comparisons,
            "warning": "Observational one-session stock returns, not an allocation-matched portfolio simulation; no fees, broker fills or verified forward trading."}
