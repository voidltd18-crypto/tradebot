"""V19.0.5 — Stock soft-exit age guard.

Safety-only wrapper for existing time-based stock exits. A missing position age
must never be interpreted as an ancient position and trigger an automatic soft
sell. Hard stops, manual sells, profit protection, entries, sizing and crypto
are unchanged.
"""
from __future__ import annotations

from fastapi import Request

VERSION = "V19.0.5"
_UNKNOWN_AGE = 999999


def _age_unknown(position) -> bool:
    try:
        raw = position.get("minutesSinceBuy")
        if raw is None:
            return True
        return int(raw) >= _UNKNOWN_AGE
    except Exception:
        return True


def install_v1905_stock_stall_age_guard(app, m) -> None:
    original_stall = m.should_stall_exit
    original_stale = getattr(m, "_v18341_stale_exit_guard", None)

    def should_stall_exit_safe(position):
        if _age_unknown(position):
            return False, "stall exit blocked: position age unavailable"
        return original_stall(position)

    m.should_stall_exit = should_stall_exit_safe

    if callable(original_stale):
        def stale_exit_safe(position):
            if _age_unknown(position):
                return False, "stale exit blocked: position age unavailable"
            return original_stale(position)
        m._v18341_stale_exit_guard = stale_exit_safe

    @app.get("/v19/stock-soft-exit-age-guard")
    def api_stock_soft_exit_age_guard(request: Request):
        m.verify_api_key(request)
        return {
            "ok": True,
            "version": VERSION,
            "unknownAgeSentinel": _UNKNOWN_AGE,
            "stallUnknownAgeAutoSellBlocked": True,
            "staleUnknownAgeAutoSellBlocked": bool(callable(original_stale)),
            "hardStopsChanged": False,
            "manualSellsChanged": False,
            "entriesChanged": False,
        }

    print(
        f"{VERSION} STOCK SOFT EXIT AGE GUARD | "
        "unknown_age_stall_sell=BLOCKED unknown_age_stale_sell=BLOCKED "
        "hard_stops=UNCHANGED entries=UNCHANGED",
        flush=True,
    )
