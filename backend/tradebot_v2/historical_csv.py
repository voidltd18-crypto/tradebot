"""Strict, offline ingestion of externally obtained daily adjusted closes.

No downloads, network access, broker calls, or trading. Input is a trusted CSV
export with date and adjusted_close columns. Provenance is supplied explicitly.
"""
import csv
from datetime import date
from io import StringIO
from math import isfinite

from backend.tradebot_v2.backtest import DatedClose, evaluate_out_of_sample


def parse_adjusted_close_csv(csv_text: str) -> list[DatedClose]:
    if not isinstance(csv_text, str) or not csv_text.strip():
        raise ValueError("Empty historical data")
    reader = csv.DictReader(StringIO(csv_text))
    if not reader.fieldnames or set(reader.fieldnames) != {"date", "adjusted_close"}:
        raise ValueError("Expected exactly date,adjusted_close CSV columns")
    rows = []
    for row in reader:
        try:
            day = date.fromisoformat(row["date"])
            price = float(row["adjusted_close"])
        except (ValueError, TypeError, KeyError):
            raise ValueError("Invalid dated adjusted close") from None
        if not isfinite(price) or price <= 0:
            raise ValueError("Invalid adjusted close")
        if rows and day <= rows[-1].day:
            raise ValueError("Duplicate or unsorted dates")
        rows.append(DatedClose(day, price))
    if not rows:
        raise ValueError("No historical rows")
    return rows


def evaluate_csv(symbol: str, csv_text: str, *, source: str, training_end: date,
                 forward_bars: int = 5, roundtrip_fee_bps: float = 20.0):
    """Pass verified provenance and explicit cutoff to the offline evaluator."""
    return evaluate_out_of_sample(
        symbol, parse_adjusted_close_csv(csv_text), source=source,
        training_end=training_end, forward_bars=forward_bars,
        roundtrip_fee_bps=roundtrip_fee_bps,
    )
