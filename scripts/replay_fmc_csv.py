"""Offline FMC CSV replay adapter. Does not connect to Alpaca or place orders.

Input CSV columns: timestamp, close; timestamp must be ISO 8601 with offset.
CSV must come from an independently verified provider. File provenance
must be supplied explicitly by the operator; no claim of validation.
"""
import argparse
import csv
import json
from pathlib import Path

from backend.stock_momentum_cost_model import compare_costed_exits


def load_bars_csv(path, *, max_rows=5000):
    observations = []
    with open(path, newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"timestamp", "close"}.issubset(reader.fieldnames):
            raise ValueError("CSV requires timestamp and close columns")
        for row in reader:
            if len(observations) >= max_rows:
                raise ValueError("too many rows; select a smaller chronological interval")
            observations.append({"timestamp": row["timestamp"], "price": row["close"]})
    if not observations:
        raise ValueError("no CSV rows")
    return observations


def run_csv_replay(path, *, symbol, source, entry_price):
    if symbol.strip().upper() != "FMC":
        raise ValueError("this adapter is restricted to FMC")
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source provenance must be provided")
    result = compare_costed_exits(entry_price, load_bars_csv(path))
    result["symbol"] = "FMC"
    result["sourceDescription"] = source.strip()
    result["dataVerifiedAsFmcHistory"] = False
    result["dataQualityWarning"] = (
        "Close prices are sampled bar closes, not executable bid/ask quotes. "
        "Provenance is operator supplied and NOT independently verified. "
        "No live or paper orders have been placed."
    )
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_file", type=Path)
    parser.add_argument("--symbol", default="FMC")
    parser.add_argument("--source", required=True, help="Provider, URL or export description")
    parser.add_argument("--entry-price", required=True, type=float)
    args = parser.parse_args()
    print(json.dumps(run_csv_replay(args.csv_file, symbol=args.symbol,
                                    source=args.source, entry_price=args.entry_price), indent=2))


if __name__ == "__main__":
    main()
