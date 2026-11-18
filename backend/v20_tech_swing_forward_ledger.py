"""Aggregate archived point-in-time candidate snapshots, without trading."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def summarize_snapshots(paths):
    records = {}
    for path in paths:
        item = json.loads(Path(path).read_text(encoding="utf-8"))
        if item.get("schemaVersion") != 1 or item.get("researchOnly") is not True or item.get("ordersSubmitted") != 0 or item.get("buyEnabled") is not False:
            raise ValueError(f"Unsafe or unrecognized snapshot: {path}")
        day = item["lastCompletedCommonBar"]
        if day in records:
            if records[day]["preview"] != item["preview"]:
                raise ValueError(f"Conflicting snapshots for {day}")
            continue
        records[day] = item
    ordered = [records[day] for day in sorted(records)]
    return {"researchOnly": True, "ordersSubmitted": 0, "buyEnabled": False,
            "uniqueDatedSnapshots": len(ordered),
            "candidateHistory": [{"day": x["lastCompletedCommonBar"],
                                  "topCandidate": x["preview"]["topCandidate"]}
                                 for x in ordered],
            "forwardSessionsValidated": 0,
            "note": "Dated candidate snapshots are observations, not performance-validated trading sessions. Do not increment release gate automatically."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshots", nargs="+")
    parser.add_argument("--output", default="swing-forward-summary.json")
    args = parser.parse_args()
    report = summarize_snapshots(args.snapshots)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
