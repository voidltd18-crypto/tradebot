"""Create a point-in-time research candidate snapshot; no broker access.

Run after US market close. This report records a signal, not a simulated fill.
Forward results require later snapshots and cannot be inferred from backtests.
"""
from __future__ import annotations
import argparse
import json
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from backend.v20_tech_swing_research import Bar, UNIVERSE
from backend.v20_tech_swing_candidate_preview import candidate_preview


def make_snapshot(history, *, recorded_at=None):
    now = recorded_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("recorded_at must include timezone")
    if not history:
        raise ValueError("No price history")
    # Only common completed trading days; don't mix symbol timestamps.
    common = set.intersection(*(set(b.day for b in bars) for bars in history.values()))
    if not common:
        raise ValueError("No common trading date")
    last = max(common)
    if last > now.date():
        raise ValueError("Future data detected")
    if (now.date() - last).days > 7:
        raise ValueError("Stale price history")
    # On the same UTC calendar day, US session may still be open. Refuse to
    # infer completion from current time; use previous day's bars instead.
    if last == now.date():
        previous = [d for d in common if d < last]
        if not previous:
            raise ValueError("No prior completed daily bar")
        last = max(previous)
    filtered = {sym: [b for b in bars if b.day <= last] for sym, bars in history.items()}
    preview = candidate_preview(filtered, as_of=last)
    return {"schemaVersion": 1, "researchOnly": True, "ordersSubmitted": 0,
            "buyEnabled": False, "recordedAtUtc": now.isoformat(),
            "lastCompletedCommonBar": last.isoformat(), "preview": preview,
            "forwardSessionsValidated": 0,
            "warning": "One dated snapshot is not forward validation or evidence of a fill."}


def fetch_daily_history():
    import yfinance as yf
    history = {}
    for symbol in sorted(UNIVERSE - {"GOOG"}):
        frame = yf.download(symbol, period="3y", interval="1d", auto_adjust=True,
                            progress=False, threads=False)
        if frame.empty:
            raise RuntimeError(f"Missing bars for {symbol}")
        if getattr(frame.columns, "nlevels", 1) > 1:
            frame.columns = frame.columns.get_level_values(0)
        history[symbol] = [Bar(day.date(), float(row["Open"]), float(row["High"]),
                               float(row["Low"]), float(row["Close"]), float(row["Volume"]))
                           for day, row in frame.iterrows()]
    return history


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="swing-forward-snapshots")
    args = parser.parse_args()
    snapshot = make_snapshot(fetch_daily_history())
    folder = Path(args.output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    # Artifacts can be retained and compared in future, but do not pretend
    # GitHub Actions artifacts alone constitute a persistent 60-session ledger.
    filename = folder / ("candidate-" + snapshot["lastCompletedCommonBar"] + ".json")
    filename.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshotPath": str(filename),
                      "lastCompletedCommonBar": snapshot["lastCompletedCommonBar"],
                      "topCandidate": snapshot["preview"]["topCandidate"],
                      "ordersSubmitted": 0}, indent=2))


if __name__ == "__main__":
    main()
