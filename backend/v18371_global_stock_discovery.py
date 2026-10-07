"""V18.3.71 Global Stock Discovery.

Market-wide Alpaca discovery for the existing live stock entry engine.
Trading thresholds, AI gates, sizing, orders and exits are unchanged.
"""
from __future__ import annotations
import os
import threading
import time
from datetime import UTC, datetime
from typing import Any, Dict, List
import requests

REFRESH_SECONDS = max(300, int(os.getenv("TRADEBOT_GLOBAL_STOCK_REFRESH_SECONDS", "900")))
ACTIVE_SIZE = max(6, min(30, int(os.getenv("TRADEBOT_GLOBAL_STOCK_ACTIVE_SIZE", "12"))))
VALIDATE_LIMIT = max(ACTIVE_SIZE, min(100, int(os.getenv("TRADEBOT_GLOBAL_STOCK_VALIDATE_LIMIT", "45"))))
REQUEST_TIMEOUT = max(3.0, min(15.0, float(os.getenv("TRADEBOT_GLOBAL_STOCK_TIMEOUT_SECONDS", "7"))))
_lock = threading.Lock()
_runtime: Dict[str, Any] = {
    "lastRefresh": None, "lastRefreshEpoch": 0.0, "discoveredCount": 0,
    "validatedCount": 0, "activeCount": 0, "heldCount": 0,
    "source": "Alpaca market-wide screeners", "sourceErrors": [], "rows": [],
}

def _now() -> str:
    return datetime.now(UTC).isoformat()

def _headers(m) -> Dict[str, str]:
    return {
        "APCA-API-KEY-ID": str(getattr(m, "API_KEY", "") or ""),
        "APCA-API-SECRET-KEY": str(getattr(m, "API_SECRET", "") or ""),
        "Accept": "application/json",
    }

def _get_json(m, url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    r = requests.get(url, headers=_headers(m), params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    payload = r.json()
    return payload if isinstance(payload, dict) else {}

def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)

def _discover(m):
    scores: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    try:
        payload = _get_json(m, "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives", {"by": "volume", "top": 100})
        rows = payload.get("most_actives") or payload.get("mostActives") or payload.get("data") or []
        if isinstance(rows, list):
            for rank, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").upper().strip()
                if not symbol:
                    continue
                item = scores.setdefault(symbol, {"symbol": symbol, "score": 0.0, "sources": [], "volume": 0.0, "changePct": 0.0})
                item["score"] += max(1.0, 120.0 - rank)
                item["volume"] = max(item["volume"], _num(row.get("volume")))
                item["sources"].append("most-active")
    except Exception as exc:
        errors.append(f"most-actives: {exc}")

    try:
        payload = _get_json(m, "https://data.alpaca.markets/v1beta1/screener/stocks/movers", {"top": 50})
        rows = payload.get("gainers") or []
        if isinstance(rows, list):
            for rank, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                symbol = str(row.get("symbol") or "").upper().strip()
                if not symbol:
                    continue
                pct = _num(row.get("percent_change", row.get("percentage_change", row.get("change_pct", 0.0))))
                item = scores.setdefault(symbol, {"symbol": symbol, "score": 0.0, "sources": [], "volume": 0.0, "changePct": 0.0})
                item["score"] += max(1.0, 180.0 - rank * 2.0) + max(0.0, pct) * 3.0
                item["changePct"] = max(item["changePct"], pct)
                item["sources"].append("gainer")
    except Exception as exc:
        errors.append(f"movers: {exc}")

    discovered_count = len(scores)
    ranked = sorted(scores.values(), key=lambda row: (-_num(row.get("score")), -_num(row.get("volume")), row.get("symbol", "")))
    validated: List[Dict[str, Any]] = []
    min_price = _num(getattr(m, "AUTO_UNIVERSE_MIN_PRICE", 1.0), 1.0)
    max_price = _num(getattr(m, "AUTO_UNIVERSE_MAX_PRICE", 800.0), 800.0)
    max_spread = _num(getattr(m, "AUTO_UNIVERSE_MAX_SPREAD", 0.020), 0.020)

    for row in ranked[:VALIDATE_LIMIT]:
        symbol = row["symbol"]
        if not symbol.replace("-", "").isalnum() or len(symbol) > 6:
            continue
        try:
            quote = m.get_quote(symbol)
            price = _num(quote.get("mid"))
            spread = _num(quote.get("spread"), 999.0)
            if price < min_price or price > max_price or spread > max_spread:
                continue
            sources = "+".join(dict.fromkeys(row.get("sources") or []))
            validated.append({
                "symbol": symbol,
                "score": round(_num(row.get("score")), 4),
                "reason": f"GLOBAL {sources} | price={price:.2f} | spread={spread:.4f} | move={_num(row.get('changePct')):.2f}% | volume={int(_num(row.get('volume'))):,}",
                "status": "active", "adaptiveSource": "GLOBAL",
                "price": round(price, 4), "spread": round(spread, 6),
                "changePct": round(_num(row.get("changePct")), 4),
                "volume": int(_num(row.get("volume"))),
            })
        except Exception:
            continue
    return validated, errors, discovered_count

def _held_rows(m):
    rows = []
    try:
        for p in m.get_all_positions():
            symbol = str(p.get("symbol") or "").upper().strip()
            if symbol and "/" not in symbol:
                rows.append({
                    "symbol": symbol, "score": 10000.0,
                    "reason": "currently held position - retained for live management",
                    "status": "active", "adaptiveSource": "HELD",
                })
    except Exception:
        pass
    return rows

def _fallback_rows(m, seen, slots):
    rows = []
    fallback = list(getattr(m, "SAFE_UNIVERSE", []) or []) + list(getattr(m, "current_universe", []) or [])
    for symbol in fallback:
        symbol = str(symbol or "").upper().strip()
        if not symbol or symbol in seen:
            continue
        rows.append({
            "symbol": symbol, "score": 0.0,
            "reason": "fallback core symbol - global screener did not fill all slots",
            "status": "active", "adaptiveSource": "FALLBACK",
        })
        seen.add(symbol)
        if len(rows) >= slots:
            break
    return rows

def _refresh(m, force=False):
    with _lock:
        now = time.time()
        last = _num(_runtime.get("lastRefreshEpoch"))
        if not force and last > 0 and (now - last) < REFRESH_SECONDS:
            return {"ok": True, "message": "Global stock universe still fresh", "symbols": list(getattr(m, "current_universe", []) or []), "rows": list(_runtime.get("rows") or [])}

        validated, errors, discovered_count = _discover(m)
        held = _held_rows(m)
        chosen = []
        seen = set()
        for row in held:
            if row["symbol"] not in seen:
                chosen.append(row)
                seen.add(row["symbol"])

        entry_added = 0
        for row in validated:
            if row["symbol"] in seen:
                continue
            chosen.append(row)
            seen.add(row["symbol"])
            entry_added += 1
            if entry_added >= ACTIVE_SIZE:
                break

        if entry_added < ACTIVE_SIZE:
            chosen.extend(_fallback_rows(m, seen, ACTIVE_SIZE - entry_added))

        symbols = [row["symbol"] for row in chosen]
        m.current_universe = symbols
        m.last_universe_refresh_ts = now
        for symbol in symbols:
            try:
                m.ensure_symbol_state(symbol, custom=symbol in getattr(m, "custom_symbols", {}))
            except Exception:
                pass
        try:
            m.save_weekly_universe(chosen, "V18.3.71 global market refresh")
        except Exception:
            pass

        _runtime.update({
            "lastRefresh": _now(), "lastRefreshEpoch": now,
            "discoveredCount": discovered_count, "validatedCount": len(validated),
            "activeCount": len(symbols), "heldCount": len(held),
            "sourceErrors": errors[-5:], "rows": chosen,
        })
        print(
            "V18.3.71 GLOBAL STOCK DISCOVERY | "
            f"discovered={discovered_count} validated={len(validated)} "
            f"entry_slots={entry_added}/{ACTIVE_SIZE} held={len(held)} active={len(symbols)} "
            f"refresh={REFRESH_SECONDS // 60}m errors={len(errors)} symbols={','.join(symbols)}"
        )
        return {
            "ok": True,
            "message": f"Global stock universe refreshed with {entry_added} ranked entry candidates",
            "symbols": symbols, "rows": chosen,
            "discoveredCount": discovered_count, "validatedCount": len(validated),
            "sourceErrors": errors,
        }

def install_v18371_global_stock_discovery(app, m) -> None:
    def build_weekly_universe(force=False):
        return _refresh(m, force=force)
    def refresh_universe_if_needed(force=False):
        return _refresh(m, force=force)
    def auto_universe_payload():
        rows = list(_runtime.get("rows") or [])
        return {
            "enabled": True, "mode": "GLOBAL_OPEN_MARKET", "size": ACTIVE_SIZE,
            "activeSymbols": list(getattr(m, "current_universe", []) or []),
            "rows": rows, "lastRefresh": _runtime.get("lastRefresh"),
            "refreshSeconds": REFRESH_SECONDS,
            "discoveryCount": int(_runtime.get("discoveredCount") or 0),
            "validatedCount": int(_runtime.get("validatedCount") or 0),
            "coreCount": sum(1 for row in rows if row.get("adaptiveSource") == "FALLBACK"),
            "heldCount": int(_runtime.get("heldCount") or 0),
            "source": _runtime.get("source"),
            "sourceErrors": list(_runtime.get("sourceErrors") or []),
            "globalDiscovery": True,
            "candidatePoolSize": int(_runtime.get("discoveredCount") or 0),
            "keepWinners": True,
        }

    m.build_weekly_universe = build_weekly_universe
    m.refresh_universe_if_needed = refresh_universe_if_needed
    m.auto_universe_payload = auto_universe_payload
    m.weekly_universe_public = auto_universe_payload
    m.AUTO_UNIVERSE_ENABLED = True
    m.AUTO_UNIVERSE_SIZE = ACTIVE_SIZE
    m.AUTO_UNIVERSE_MIN_HOURS_BETWEEN_REFRESH = REFRESH_SECONDS / 3600.0
    m.UNIVERSE_REFRESH_SECONDS = REFRESH_SECONDS
    print(
        "V18.3.71 GLOBAL STOCK DISCOVERY | installed "
        f"active_size={ACTIVE_SIZE} refresh={REFRESH_SECONDS // 60}m "
        "sources=Alpaca most-actives+gainers live_entry_logic=UNCHANGED"
    )
