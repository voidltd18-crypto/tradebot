"""Persistent, observational crypto price peaks, not verified since-entry highs.

This module deliberately does not place orders or authorise trading.
A position seen for the first time may have reached a higher price before
observation began. Such peaks must not be passed as a verified since-entry high.
"""
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


def _positive(value):
    try:
        n = Decimal(str(value))
        return n if n.is_finite() and n > 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _ensure(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS v19_crypto_observed_peaks (
        position_id TEXT PRIMARY KEY,
        symbol TEXT NOT NULL,
        first_seen TEXT NOT NULL,
        last_seen TEXT NOT NULL,
        observed_peak TEXT NOT NULL,
        observations INTEGER NOT NULL
    )""")


def observe_position_peak(db_path, *, symbol, entry, quantity, observed_price, observed_at=None):
    """Store a maximum for one observed position identity, across restarts.

    Observed prices are indicative snapshots, not executable bids. New lots,
    quantity changes, or entry changes produce a new observation identity.
    """
    symbol = str(symbol or "").strip().upper()
    entry_n, quantity_n, observed_n = (_positive(x) for x in (entry, quantity, observed_price))
    if not symbol or not (symbol.endswith("USD") or symbol.endswith("USDT")) or any(
        x is None for x in (entry_n, quantity_n, observed_n)
    ):
        return {"status": "unverified", "reason": "missing or invalid position observation"}
    stamp = observed_at or datetime.now(timezone.utc)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return {"status": "unverified", "reason": "observation time must be timezone-aware"}
    at = stamp.astimezone(timezone.utc).isoformat()
    identity = f"{symbol}:{entry_n}:{quantity_n}"
    with sqlite3.connect(db_path, timeout=15) as conn:
        _ensure(conn)
        row = conn.execute("SELECT observed_peak, first_seen, observations FROM v19_crypto_observed_peaks WHERE position_id=?", (identity,)).fetchone()
        if row:
            peak = max(Decimal(row[0]), observed_n)
            first_seen = row[1]
            observations = row[2] + 1
            conn.execute("UPDATE v19_crypto_observed_peaks SET observed_peak=?, last_seen=?, observations=? WHERE position_id=?",
                         (str(peak), at, observations, identity))
        else:
            peak = observed_n
            first_seen = at
            observations = 1
            conn.execute("INSERT INTO v19_crypto_observed_peaks VALUES (?, ?, ?, ?, ?, ?)",
                         (identity, symbol, at, at, str(peak), observations))
    return {"status": "observed", "symbol": symbol, "observedPeak": str(peak),
            "firstSeen": first_seen, "lastSeen": at, "observations": observations,
            "verifiedSinceEntry": False, "executableBid": False,
            "eligibleForAutomaticExit": False}
