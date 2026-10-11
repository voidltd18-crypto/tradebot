"""V19 Crypto V2 clean rebuild.

Fresh crypto engine built independently of the legacy V18 crypto stack.
It mirrors the stock-side shape: discover -> validate -> rank -> manage positions.
V19 starts in shadow mode only and never submits a live order.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import UTC, datetime
from typing import Any, Dict, List

import requests

VERSION = "V19.0.0"
REFRESH_SECONDS = 60
MAX_SHADOW_POSITIONS = 4
SHADOW_START_USD = 1000.0
SHADOW_POSITION_USD = 100.0
STOP_PCT = 1.25
TRAIL_START_PCT = 1.00
TRAIL_GIVEBACK_PCT = 0.45
MAX_SPREAD_PCT = 1.25
MIN_NOTIONAL_24H_USD = 5000.0

_lock = threading.RLock()
_started = False
_original_live_buy = None
_runtime: Dict[str, Any] = {
    "lastRefreshAt": None,
    "lastError": None,
    "cycles": 0,
    "universe": [],
    "scans": [],
    "shadowCashUsd": SHADOW_START_USD,
    "shadowRealisedPnlUsd": 0.0,
    "shadowPositions": {},
    "shadowTrades": [],
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _headers(m) -> Dict[str, str]:
    return {
        "APCA-API-KEY-ID": str(getattr(m, "API_KEY", "") or ""),
        "APCA-API-SECRET-KEY": str(getattr(m, "API_SECRET", "") or ""),
        "Accept": "application/json",
    }


def _canonical(symbol: str) -> str:
    raw = str(symbol or "").upper().strip().replace("-", "/")
    if "/" in raw:
        return raw
    if raw.endswith("USD") and len(raw) > 3:
        return f"{raw[:-3]}/USD"
    return raw


def _discover_tradable_usd(m) -> List[str]:
    symbols: List[str] = []
    assets = m.trading_client.get_all_assets()
    for asset in assets or []:
        raw = str(getattr(asset, "symbol", "") or "").upper().strip()
        asset_class = str(getattr(asset, "asset_class", "") or "").lower()
        if not raw or not bool(getattr(asset, "tradable", False)):
            continue
        if "crypto" not in asset_class and "/" not in raw:
            continue
        symbol = _canonical(raw)
        if symbol.endswith("/USD"):
            symbols.append(symbol)
    return sorted(set(symbols))


def _snapshot_batch(m, symbols: List[str]) -> Dict[str, Any]:
    if not symbols:
        return {}
    url = "https://data.alpaca.markets/v1beta3/crypto/us/latest/snapshots"
    r = requests.get(
        url,
        headers=_headers(m),
        params={"symbols": ",".join(symbols)},
        timeout=12,
    )
    r.raise_for_status()
    body = r.json() if r.content else {}
    snapshots = body.get("snapshots") if isinstance(body, dict) else {}
    return snapshots if isinstance(snapshots, dict) else {}


def _scan_symbol(symbol: str, snap: Dict[str, Any]) -> Dict[str, Any] | None:
    quote = snap.get("latestQuote") or snap.get("latest_quote") or {}
    minute = snap.get("minuteBar") or snap.get("minute_bar") or {}
    daily = snap.get("dailyBar") or snap.get("daily_bar") or {}
    prev = snap.get("prevDailyBar") or snap.get("prev_daily_bar") or {}

    bid = _num(quote.get("bp", quote.get("bid_price")))
    ask = _num(quote.get("ap", quote.get("ask_price")))
    close = _num(minute.get("c", minute.get("close")))
    if close <= 0 and bid > 0 and ask > 0:
        close = (bid + ask) / 2.0
    if close <= 0:
        close = _num(daily.get("c", daily.get("close")))
    if close <= 0:
        return None

    prev_close = _num(prev.get("c", prev.get("close")))
    change_pct = ((close / prev_close) - 1.0) * 100.0 if prev_close > 0 else 0.0
    spread_pct = ((ask - bid) / ((ask + bid) / 2.0) * 100.0) if ask > 0 and bid > 0 else 999.0
    volume = max(0.0, _num(daily.get("v", daily.get("volume"))))
    notional = volume * close

    move_component = max(-25.0, min(60.0, change_pct * 8.0))
    spread_component = max(-30.0, 22.0 - spread_pct * 12.0)
    activity_component = max(0.0, min(30.0, math.log10(max(1.0, notional)) * 4.0))
    score = move_component + spread_component + activity_component

    qualified = bool(
        change_pct > 0.0
        and spread_pct <= MAX_SPREAD_PCT
        and notional >= MIN_NOTIONAL_24H_USD
    )
    reason = (
        f"move={change_pct:.2f}% spread={spread_pct:.2f}% "
        f"notional24h=USD {notional:,.0f}"
    )
    return {
        "symbol": symbol,
        "price": round(close, 8),
        "change24hPct": round(change_pct, 4),
        "spreadPct": round(spread_pct, 4),
        "notional24hUsd": round(notional, 2),
        "score": round(score, 4),
        "qualified": qualified,
        "reason": reason,
        "source": "ALPACA_CRYPTO_SNAPSHOT",
    }


def _refresh(m) -> Dict[str, Any]:
    symbols = _discover_tradable_usd(m)
    rows: List[Dict[str, Any]] = []
    for offset in range(0, len(symbols), 40):
        batch = symbols[offset:offset + 40]
        snapshots = _snapshot_batch(m, batch)
        for symbol in batch:
            snap = snapshots.get(symbol) or snapshots.get(symbol.replace("/", "")) or {}
            if not isinstance(snap, dict):
                continue
            row = _scan_symbol(symbol, snap)
            if row:
                rows.append(row)
    rows.sort(key=lambda x: (-int(bool(x.get("qualified"))), -_num(x.get("score")), x.get("symbol", "")))
    with _lock:
        _runtime["universe"] = symbols
        _runtime["scans"] = rows
        _runtime["lastRefreshAt"] = _now()
        _runtime["lastError"] = None
        _runtime["cycles"] = int(_runtime.get("cycles") or 0) + 1
    return _payload()


def _shadow_step() -> None:
    with _lock:
        scans = list(_runtime.get("scans") or [])
        positions = dict(_runtime.get("shadowPositions") or {})
        cash = _num(_runtime.get("shadowCashUsd"), SHADOW_START_USD)
        by_symbol = {str(row.get("symbol")): row for row in scans}

        for symbol, pos in list(positions.items()):
            scan = by_symbol.get(symbol)
            if not scan:
                continue
            price = _num(scan.get("price"))
            entry = _num(pos.get("entry"))
            high = max(_num(pos.get("high"), entry), price)
            pnl_pct = ((price / entry) - 1.0) * 100.0 if entry > 0 else 0.0
            peak_pct = ((high / entry) - 1.0) * 100.0 if entry > 0 else 0.0
            giveback = ((high - price) / high) * 100.0 if high > 0 else 0.0
            pos["price"] = price
            pos["high"] = high
            pos["pnlPct"] = round(pnl_pct, 4)

            exit_reason = None
            if pnl_pct <= -STOP_PCT:
                exit_reason = "STOP"
            elif peak_pct >= TRAIL_START_PCT and giveback >= TRAIL_GIVEBACK_PCT:
                exit_reason = "TRAIL"
            elif not bool(scan.get("qualified")) and pnl_pct > 0:
                exit_reason = "MOMENTUM_FADE"

            if exit_reason:
                qty = _num(pos.get("qty"))
                proceeds = qty * price
                pnl = proceeds - _num(pos.get("notionalUsd"))
                cash += proceeds
                _runtime["shadowRealisedPnlUsd"] = _num(_runtime.get("shadowRealisedPnlUsd")) + pnl
                _runtime["shadowTrades"].append({
                    "timestamp": _now(), "symbol": symbol, "side": "SELL",
                    "price": round(price, 8), "qty": round(qty, 12),
                    "pnlUsd": round(pnl, 4), "pnlPct": round(pnl_pct, 4),
                    "reason": exit_reason,
                })
                positions.pop(symbol, None)

        slots = max(0, MAX_SHADOW_POSITIONS - len(positions))
        if slots > 0:
            candidates = [
                row for row in scans
                if bool(row.get("qualified")) and str(row.get("symbol")) not in positions
            ]
            for row in candidates[:slots]:
                spend = min(SHADOW_POSITION_USD, cash)
                price = _num(row.get("price"))
                if spend < 1.0 or price <= 0:
                    break
                qty = spend / price
                symbol = str(row.get("symbol"))
                positions[symbol] = {
                    "symbol": symbol,
                    "entry": price,
                    "price": price,
                    "high": price,
                    "qty": qty,
                    "notionalUsd": spend,
                    "openedAt": _now(),
                    "pnlPct": 0.0,
                    "entryScore": _num(row.get("score")),
                }
                cash -= spend
                _runtime["shadowTrades"].append({
                    "timestamp": _now(), "symbol": symbol, "side": "BUY",
                    "price": round(price, 8), "qty": round(qty, 12),
                    "notionalUsd": round(spend, 2),
                    "reason": "TOP_RANKED_QUALIFIED",
                })

        _runtime["shadowPositions"] = positions
        _runtime["shadowCashUsd"] = cash
        _runtime["shadowTrades"] = list(_runtime.get("shadowTrades") or [])[-200:]


def _payload() -> Dict[str, Any]:
    with _lock:
        scans = list(_runtime.get("scans") or [])
        positions = list((dict(_runtime.get("shadowPositions") or {})).values())
        cash = _num(_runtime.get("shadowCashUsd"))
        unrealised = 0.0
        for pos in positions:
            unrealised += (_num(pos.get("price")) - _num(pos.get("entry"))) * _num(pos.get("qty"))
        return {
            "ok": True,
            "version": VERSION,
            "mode": "SHADOW_ONLY",
            "liveOrders": False,
            "lastRefreshAt": _runtime.get("lastRefreshAt"),
            "lastError": _runtime.get("lastError"),
            "cycles": int(_runtime.get("cycles") or 0),
            "discovered": len(_runtime.get("universe") or []),
            "scanned": len(scans),
            "qualified": sum(1 for row in scans if bool(row.get("qualified"))),
            "scans": scans,
            "shadow": {
                "startingCashUsd": SHADOW_START_USD,
                "cashUsd": round(cash, 2),
                "realisedPnlUsd": round(_num(_runtime.get("shadowRealisedPnlUsd")), 2),
                "unrealisedPnlUsd": round(unrealised, 2),
                "positions": positions,
                "trades": list(_runtime.get("shadowTrades") or [])[-50:],
                "maxPositions": MAX_SHADOW_POSITIONS,
                "positionUsd": SHADOW_POSITION_USD,
            },
            "rules": {
                "maxSpreadPct": MAX_SPREAD_PCT,
                "minNotional24hUsd": MIN_NOTIONAL_24H_USD,
                "stopPct": STOP_PCT,
                "trailStartPct": TRAIL_START_PCT,
                "trailGivebackPct": TRAIL_GIVEBACK_PCT,
            },
        }


def _worker(m) -> None:
    time.sleep(8)
    while True:
        try:
            _refresh(m)
            _shadow_step()
            print(
                f"{VERSION} CRYPTO V2 | discovered={len(_runtime.get('universe') or [])} "
                f"scanned={len(_runtime.get('scans') or [])} "
                f"qualified={sum(1 for r in (_runtime.get('scans') or []) if r.get('qualified'))} "
                f"shadow_positions={len(_runtime.get('shadowPositions') or {})} live_orders=False",
                flush=True,
            )
        except Exception as exc:
            with _lock:
                _runtime["lastError"] = str(exc)[:500]
            print(f"{VERSION} CRYPTO V2 ERROR | {exc}", flush=True)
        time.sleep(REFRESH_SECONDS)


def install_v190_crypto_v2(app, m) -> None:
    global _started, _original_live_buy

    m.V18232_CRYPTO_SHADOW_ENABLED = False
    m.V18307_SHADOW_EXTERNAL_MARKETS_ENABLED = False

    if hasattr(m, "_v18234_live_buy"):
        _original_live_buy = m._v18234_live_buy

        def _legacy_crypto_buy_disabled(*args, **kwargs):
            print(f"{VERSION} LEGACY CRYPTO BUY BLOCKED | reset_active=True", flush=True)
            return False

        m._v18234_live_buy = _legacy_crypto_buy_disabled

    @app.get("/v19/crypto-v2")
    def crypto_v2_status():
        return _payload()

    @app.post("/v19/crypto-v2/refresh")
    def crypto_v2_refresh():
        result = _refresh(m)
        _shadow_step()
        return result

    if not _started:
        _started = True
        threading.Thread(target=_worker, args=(m,), daemon=True, name="v19-crypto-v2-shadow").start()

    print(
        f"{VERSION} CRYPTO CLEAN REBUILD | old_shadow=OFF old_live_entries=BLOCKED "
        "legacy_exit_protection=ON new_engine=SHADOW_ONLY stock_logic=UNCHANGED",
        flush=True,
    )
