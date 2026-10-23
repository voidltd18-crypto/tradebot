"""Read-only quality-score vs forward price movement analysis.

Usage: python -m backend.analysis.quality_forward_outcomes /var/data/tradebot.db
Does not claim the outcomes are realised execution profits.
"""
import argparse
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

BANDS = ((0.0, 0.03), (0.03, 0.05), (0.05, 0.10), (0.10, float("inf")))

def analyse(connection, due_minutes=None):
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if "v179_decision_audit" not in tables:
        return {"ok": False, "reason": "v179_decision_audit table unavailable"}
    sql = ("SELECT quality, return_pct, due_minutes, decision_id "
           "FROM v179_decision_audit WHERE status='COMPLETED' "
           "AND quality IS NOT NULL AND return_pct IS NOT NULL")
    params = []
    if due_minutes is not None:
        sql += " AND due_minutes=?"
        params.append(due_minutes)
    groups = defaultdict(list)
    for quality, movement, horizon, decision_id in connection.execute(sql, params):
        q, m = float(quality), float(movement)
        if not (-10 <= q <= 10 and -1000 <= m <= 1000):
            continue
        band = next((f"{lo:.2f}–{hi:.2f}" if hi != float("inf") else "0.10+"
                     for lo, hi in BANDS if lo <= q < hi), "other")
        groups[(int(horizon), band)].append(m)
    results = []
    for (horizon, band), returns in sorted(groups.items()):
        ordered = sorted(returns)
        results.append({
            "dueMinutes": horizon, "qualityBand": band, "samples": len(ordered),
            "positivePct": round(100 * sum(x > 0 for x in ordered) / len(ordered), 2),
            "meanForwardReturnPct": round(sum(ordered) / len(ordered), 4),
            "medianForwardReturnPct": round(ordered[len(ordered)//2], 4),
        })
    return {"ok": True, "measurement": "forward quote movement, NOT realised trade P&L",
            "thresholdUnchanged": 0.10, "groups": results}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("db", type=Path)
    p.add_argument("--horizon", type=int, default=None)
    args = p.parse_args()
    if not args.db.is_file():
        p.error("database path does not exist")
    uri = f"file:{args.db.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        print(json.dumps(analyse(conn, args.horizon), indent=2))

if __name__ == "__main__":
    main()
