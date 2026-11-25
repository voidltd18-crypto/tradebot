"""Build a reproducible, read-only report from archived daily snapshots."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from backend.v20_tech_swing_forward_outcomes import evaluate_observations
from backend.v20_tech_swing_forward_benchmark import compare_to_tech_basket
from backend.v20_tech_swing_forward_snapshot import fetch_daily_history


def build_report(paths, history):
    outcomes = evaluate_observations(paths, history)
    benchmark = compare_to_tech_basket(outcomes, history)
    return {"researchOnly": True, "ordersSubmitted": 0, "buyEnabled": False,
            "uniqueDatedSnapshots": outcomes["uniqueDatedSnapshots"],
            "observedSignals": outcomes["observedSignals"],
            "benchmarkComparableSignals": benchmark["comparableSignals"],
            "meanExcessVsTechPctPoints": benchmark["meanExcessPctPoints"],
            "forwardSessionsValidated": 0,
            "observations": outcomes["observations"],
            "benchmarkComparisons": benchmark["comparisons"],
            "warning": "Research observations only. This does not establish live-trading readiness or authorize orders."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", default="swing-forward-snapshots")
    parser.add_argument("--output", default="swing-forward-report.json")
    args = parser.parse_args()
    paths = sorted(Path(args.snapshot_dir).glob("candidate-*.json"))
    if not paths:
        raise SystemExit("No archived snapshots found; cannot fabricate forward results")
    report = build_report(paths, fetch_daily_history())
    Path(args.output).write_text(json.dumps(report, indent=2)+chr(10), encoding="utf-8")
    print(json.dumps({"snapshots": report["uniqueDatedSnapshots"],
                      "observedSignals": report["observedSignals"],
                      "benchmarkComparableSignals": report["benchmarkComparableSignals"],
                      "ordersSubmitted": 0}, indent=2))


if __name__ == "__main__":
    main()
