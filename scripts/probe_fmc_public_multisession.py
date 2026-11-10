"""Compare FMC exit candidates over several REAL one-minute public chart sessions.

The entry at each session's FIRST one-minute close is entirely hypothetical.
This is a no-credential research probe, NOT Alpaca historical verification.
No broker calls, no orders. Never claim these are actual user's fills.
"""
import json
from collections import defaultdict
from datetime import datetime

from backend.stock_momentum_cost_model import compare_costed_exits
from backend.stock_momentum_endofday_audit import full_session_comparison
from scripts.probe_fmc_public_intraday import get_intraday_fmc


def evaluate_sessions(sessions):
    if not isinstance(sessions, dict) or not sessions:
        raise ValueError("sessions required")
    records = []
    for session, bars in sorted(sessions.items()):
        if len(bars) < 30:
            continue
        entry = bars[0]["price"]
        result = compare_costed_exits(entry, bars)
        configured = compare_costed_exits(entry, bars, reference_activation_pct=1.2)
        audit = full_session_comparison(entry, bars)
        candidate = result["candidate"]
        reference = result["referenceTrailingExit"]
        records.append({
            "session": session, "observations": len(bars),
            "hypotheticalEntry": round(entry, 6),
            "candidateStatus": candidate["status"],
            "referenceStatus": reference["status"],
            "candidateNetReturnPct": candidate["netReturnPct"],
            "referenceNetReturnPct": reference["netReturnPct"],
            "netPnlDifferenceUsdPerShare": result["candidateMinusReferenceNetPnlUsd"],
            "ordersSubmitted": 0,
            "assumedEndOfDay": audit,
            "configuredReferenceStatus": configured["referenceTrailingExit"]["status"],
            "configuredReferenceNetReturnPct": configured["referenceTrailingExit"]["netReturnPct"],
            "candidateVersusConfiguredReferenceUsd": configured["candidateMinusReferenceNetPnlUsd"],
        })
    comparable = [r for r in records if r["netPnlDifferenceUsdPerShare"] is not None]
    all_outcomes = [r['assumedEndOfDay'] for r in records]
    complete = [o for o in all_outcomes if o['candidateMinusReferenceUsd'] is not None]
    configured_pairs = [r for r in records if r["candidateVersusConfiguredReferenceUsd"] is not None]
    return {
        "source": "unofficial Yahoo 1m FMC chart closes",
        "entryRule": "hypothetical first minute-close entry for each session",
        "readOnly": True, "ordersSubmitted": 0,
        "paperOrLiveVerified": False,
        "sessions": records,
        "comparableSessions": len(comparable),
        "assumedCloseComparableSessions": len(complete),
        "assumedCloseSpikeBetter": sum(o["candidateMinusReferenceUsd"] > 0 for o in complete),
        "assumedCloseReferenceBetter": sum(o["candidateMinusReferenceUsd"] < 0 for o in complete),
        "assumedCloseTies": sum(o["candidateMinusReferenceUsd"] == 0 for o in complete),
        "configuredReferenceActivationPct": 1.2,
        "configuredReferenceComparable": len(configured_pairs),
        "configuredReferenceWins": sum(r["candidateVersusConfiguredReferenceUsd"] < 0 for r in configured_pairs),
        "configuredCandidateWins": sum(r["candidateVersusConfiguredReferenceUsd"] > 0 for r in configured_pairs),
        "configuredTies": sum(r["candidateVersusConfiguredReferenceUsd"] == 0 for r in configured_pairs),
        "spikeBetter": sum(r["netPnlDifferenceUsdPerShare"] > 0 for r in comparable),
        "referenceBetter": sum(r["netPnlDifferenceUsdPerShare"] < 0 for r in comparable),
        "ties": sum(r["netPnlDifferenceUsdPerShare"] == 0 for r in comparable),
        "blockedReleaseReasons": [
            "Hypothetical entries do not match verified broker fills",
            "Unofficial prices not executable bids/asks",
            "Small non-random historical sample and simplified baseline",
            "Paper brokerage executions unverified",
        ],
        "releaseReady": False,
    }


def main():
    import urllib.request
    import json as _json
    from scripts.probe_fmc_public_intraday import URL
    request = urllib.request.Request(
        URL, headers={"User-Agent": "Mozilla/5.0",
                      "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = _json.load(response)
        item = payload["chart"]["result"][0]
        assert item["meta"]["symbol"] == "FMC"
        times = item["timestamp"]
        closes = item["indicators"]["quote"][0]["close"]
        assert len(times) == len(closes)
    except Exception:
        raise RuntimeError("FMC minute history unavailable or malformed") from None
    sessions = defaultdict(list)
    from datetime import timezone
    from math import isfinite
    for t, c in zip(times, closes):
        if c is None:
            continue
        price = float(c)
        if not isfinite(price) or price <= 0:
            raise ValueError("invalid close")
        timestamp = datetime.fromtimestamp(int(t), timezone.utc)
        # US regular session 14:30–21:00 UTC in November 2026.
        if timestamp.strftime("%H:%M") < "14:30" or timestamp.strftime("%H:%M") > "21:00":
            continue
        date = timestamp.date().isoformat()
        rows = sessions[date]
        if rows and timestamp <= datetime.fromisoformat(rows[-1]["timestamp"]):
            raise ValueError("non-chronological observations")
        rows.append({"timestamp": timestamp.isoformat(), "price": price})
    report = evaluate_sessions(sessions)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
