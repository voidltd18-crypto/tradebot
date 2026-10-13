"""V19.0.5 — Stock position-age safety.

Prevents missing in-memory BUY history after a restart/deploy from being treated
as an ancient 999999-minute position by time-based stock exits.

This module does not add order authority or change entry selection, sizing,
hard-stop thresholds, peak-profit thresholds, or crypto behaviour.
"""
from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from typing import Any, Dict, Optional

from fastapi import Request

VERSION = "V19.0.5"
_CACHE_SECONDS = 15.0
_cache_lock = threading.RLock()
_cache: Dict[str, Dict[str, Any]] = {}
_runtime: Dict[str, Any] = {
    "version": VERSION,
    "installed": False,
    "dbFallbackHits": 0,
    "unknownAgeFallbacks": 0,
    "lastDbFallbackAt": None,
    "lastUnknownAgeAt": None,
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _normalise_event(row: Any) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    try:
        d = dict(row)
    except Exception:
        return None
    return {
        "timestamp": d.get("timestamp"),
        "day": d.get("day"),
        "time": d.get("time"),
        "symbol": str(d.get("symbol") or "").upper(),
        "side": str(d.get("side") or "").upper(),
        "id": d.get("id"),
        "source": "sqlite",
    }


def _db_buy_event(m, symbol: str, *, today_only: bool) -> Optional[Dict[str, Any]]:
    sym = str(symbol or "").upper().strip()
    if not sym or not bool(getattr(m, "SQLITE_ENABLED", False)):
        return None

    today = str(m.today_str())
    cache_key = f"{sym}|{today if today_only else 'latest'}"
    now_mono = time.monotonic()
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and now_mono - float(cached.get("_cachedAt") or 0.0) < _CACHE_SECONDS:
            return cached.get("event")

    conn = None
    event = None
    try:
        m.init_db()
        conn = m.db_connect()
        if today_only:
            row = conn.execute(
                """SELECT id,timestamp,day,time,symbol,side
                   FROM trades
                   WHERE UPPER(symbol)=? AND UPPER(side)='BUY' AND day=?
                   ORDER BY timestamp DESC,id DESC LIMIT 1""",
                (sym, today),
            ).fetchone()
        else:
            row = conn.execute(
                """SELECT id,timestamp,day,time,symbol,side
                   FROM trades
                   WHERE UPPER(symbol)=? AND UPPER(side)='BUY'
                   ORDER BY timestamp DESC,id DESC LIMIT 1""",
                (sym,),
            ).fetchone()
        event = _normalise_event(row)
        if event:
            _runtime["dbFallbackHits"] = int(_runtime.get("dbFallbackHits") or 0) + 1
            _runtime["lastDbFallbackAt"] = _now()
    except Exception as exc:
        print(f"{VERSION} STOCK AGE DB FALLBACK ERROR | symbol={sym} error={exc}", flush=True)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    with _cache_lock:
        _cache[cache_key] = {"_cachedAt": now_mono, "event": event}
    return event


def _event_datetime(event: Optional[Dict[str, Any]]) -> Optional[datetime]:
    if not event:
        return None

    raw = str(event.get("timestamp") or "").strip()
    if raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt.astimezone(UTC)
        except Exception:
            pass

    day = str(event.get("day") or "").strip()
    tm = str(event.get("time") or "").strip()
    if day and tm:
        try:
            return datetime.strptime(f"{day} {tm}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except Exception:
            pass
    return None


def install_v1905_stock_age_safety(app, m) -> None:
    original_get_today_buy_event = m.get_today_buy_event
    original_today_buy_count = m.today_buy_count

    def get_today_buy_event_safe(symbol: str):
        try:
            event = original_get_today_buy_event(symbol)
            if event:
                return event
        except Exception:
            pass
        return _db_buy_event(m, symbol, today_only=True)

    def was_bought_today_safe(symbol: str) -> bool:
        return get_today_buy_event_safe(symbol) is not None

    def minutes_since_buy_safe(symbol: str) -> int:
        event = get_today_buy_event_safe(symbol)
        if event is None:
            event = _db_buy_event(m, symbol, today_only=False)

        dt = _event_datetime(event)
        if dt is None:
            # Important: never use 999999 for an unknown age. Several soft/time
            # exits interpret that as an ancient trade. One minute is the safe,
            # fail-closed value; hard stops remain unaffected.
            _runtime["unknownAgeFallbacks"] = int(_runtime.get("unknownAgeFallbacks") or 0) + 1
            _runtime["lastUnknownAgeAt"] = _now()
            return 1

        return max(1, int((datetime.now(UTC) - dt).total_seconds() / 60.0))

    def today_buy_count_safe() -> int:
        try:
            memory_count = int(original_today_buy_count() or 0)
        except Exception:
            memory_count = 0
        if not bool(getattr(m, "SQLITE_ENABLED", False)):
            return memory_count

        conn = None
        try:
            m.init_db()
            conn = m.db_connect()
            row = conn.execute(
                """SELECT COUNT(DISTINCT UPPER(symbol)) AS c
                   FROM trades
                   WHERE UPPER(side)='BUY' AND day=?""",
                (str(m.today_str()),),
            ).fetchone()
            db_count = int((row["c"] if row else 0) or 0)
            return max(memory_count, db_count)
        except Exception:
            return memory_count
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    m.get_today_buy_event = get_today_buy_event_safe
    m.was_bought_today = was_bought_today_safe
    m.minutes_since_today_buy = minutes_since_buy_safe
    m.today_buy_count = today_buy_count_safe

    @app.get("/v19/stock-age-safety")
    def api_stock_age_safety(request: Request):
        m.verify_api_key(request)
        return {
            "ok": True,
            **dict(_runtime),
            "unknownAgePolicy": "1_MINUTE_FAIL_CLOSED",
            "persistentBuyHistory": True,
            "liveTradingAuthorityAdded": False,
        }

    _runtime["installed"] = True
    print(
        f"{VERSION} STOCK AGE SAFETY | persistent_buy_history=ON "
        "unknown_age=1m time_exit_false_age=BLOCKED",
        flush=True,
    )
