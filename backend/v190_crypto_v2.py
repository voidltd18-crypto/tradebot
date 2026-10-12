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

VERSION = "V19.0.4"
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
_scan_lock = threading.Lock()
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
    "shadowEvidence": {
        "buyEvents": 0,
        "completedTrades": 0,
    },
}


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except Exception:
        return float(default)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _ensure_shadow_tables(m) -> None:
    conn = m.db_connect()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS v190_crypto_shadow_events (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   timestamp TEXT NOT NULL,
                   symbol TEXT NOT NULL,
                   side TEXT NOT NULL,
                   price REAL NOT NULL,
                   qty REAL NOT NULL,
                   notional_usd REAL,
                   entry_price REAL,
                   entry_score REAL,
                   opened_at TEXT,
                   closed_at TEXT,
                   pnl_usd REAL,
                   pnl_pct REAL,
                   reason TEXT
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS v190_crypto_shadow_positions (
                   symbol TEXT PRIMARY KEY,
                   entry REAL NOT NULL,
                   price REAL NOT NULL,
                   high REAL NOT NULL,
                   qty REAL NOT NULL,
                   notional_usd REAL NOT NULL,
                   opened_at TEXT NOT NULL,
                   pnl_pct REAL NOT NULL DEFAULT 0,
                   entry_score REAL NOT NULL DEFAULT 0
               )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS v190_crypto_shadow_meta (
                   key TEXT PRIMARY KEY,
                   value REAL NOT NULL
               )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_v190_crypto_shadow_events_side "
            "ON v190_crypto_shadow_events(side, id)"
        )
        conn.execute(
            "INSERT OR IGNORE INTO v190_crypto_shadow_meta(key,value) VALUES ('cashUsd',?)",
            (SHADOW_START_USD,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO v190_crypto_shadow_meta(key,value) VALUES ('realisedPnlUsd',0)"
        )
        conn.commit()
    finally:
        conn.close()


def _restore_shadow_state(m) -> None:
    _ensure_shadow_tables(m)
    conn = m.db_connect()
    try:
        meta = {
            str(row["key"]): _num(row["value"])
            for row in conn.execute("SELECT key,value FROM v190_crypto_shadow_meta").fetchall()
        }
        positions: Dict[str, Dict[str, Any]] = {}
        for raw in conn.execute(
            """SELECT symbol,entry,price,high,qty,notional_usd,opened_at,pnl_pct,entry_score
               FROM v190_crypto_shadow_positions"""
        ).fetchall():
            row = dict(raw)
            symbol = str(row.get("symbol") or "")
            if not symbol:
                continue
            positions[symbol] = {
                "symbol": symbol,
                "entry": _num(row.get("entry")),
                "price": _num(row.get("price")),
                "high": _num(row.get("high")),
                "qty": _num(row.get("qty")),
                "notionalUsd": _num(row.get("notional_usd")),
                "openedAt": str(row.get("opened_at") or ""),
                "pnlPct": _num(row.get("pnl_pct")),
                "entryScore": _num(row.get("entry_score")),
            }

        rows = conn.execute(
            """SELECT timestamp,symbol,side,price,qty,notional_usd,entry_price,entry_score,
                      opened_at,closed_at,pnl_usd,pnl_pct,reason
               FROM v190_crypto_shadow_events ORDER BY id DESC LIMIT 200"""
        ).fetchall()
        trades = []
        for raw in reversed(rows):
            row = dict(raw)
            trades.append({
                "timestamp": row.get("timestamp"),
                "symbol": row.get("symbol"),
                "side": row.get("side"),
                "price": _num(row.get("price")),
                "qty": _num(row.get("qty")),
                "notionalUsd": None if row.get("notional_usd") is None else _num(row.get("notional_usd")),
                "entryPrice": None if row.get("entry_price") is None else _num(row.get("entry_price")),
                "entryScore": None if row.get("entry_score") is None else _num(row.get("entry_score")),
                "openedAt": row.get("opened_at"),
                "closedAt": row.get("closed_at"),
                "pnlUsd": None if row.get("pnl_usd") is None else _num(row.get("pnl_usd")),
                "pnlPct": None if row.get("pnl_pct") is None else _num(row.get("pnl_pct")),
                "reason": row.get("reason"),
            })

        counts = conn.execute(
            """SELECT
                   SUM(CASE WHEN side='BUY' THEN 1 ELSE 0 END) AS buys,
                   SUM(CASE WHEN side='SELL' THEN 1 ELSE 0 END) AS sells
               FROM v190_crypto_shadow_events"""
        ).fetchone()
        with _lock:
            _runtime["shadowCashUsd"] = _num(meta.get("cashUsd"), SHADOW_START_USD)
            _runtime["shadowRealisedPnlUsd"] = _num(meta.get("realisedPnlUsd"))
            _runtime["shadowPositions"] = positions
            _runtime["shadowTrades"] = trades
            _runtime["shadowEvidence"] = {
                "buyEvents": int((counts["buys"] if counts else 0) or 0),
                "completedTrades": int((counts["sells"] if counts else 0) or 0),
            }
    finally:
        conn.close()


def _persist_shadow_state(
    m,
    positions: Dict[str, Dict[str, Any]],
    cash: float,
    realised_pnl: float,
    events: List[Dict[str, Any]],
) -> None:
    conn = m.db_connect()
    try:
        conn.execute("BEGIN")
        conn.execute(
            """INSERT INTO v190_crypto_shadow_meta(key,value) VALUES ('cashUsd',?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (cash,),
        )
        conn.execute(
            """INSERT INTO v190_crypto_shadow_meta(key,value) VALUES ('realisedPnlUsd',?)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
            (realised_pnl,),
        )
        conn.execute("DELETE FROM v190_crypto_shadow_positions")
        for pos in positions.values():
            conn.execute(
                """INSERT INTO v190_crypto_shadow_positions
                   (symbol,entry,price,high,qty,notional_usd,opened_at,pnl_pct,entry_score)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    str(pos.get("symbol") or ""),
                    _num(pos.get("entry")),
                    _num(pos.get("price")),
                    _num(pos.get("high")),
                    _num(pos.get("qty")),
                    _num(pos.get("notionalUsd")),
                    str(pos.get("openedAt") or _now()),
                    _num(pos.get("pnlPct")),
                    _num(pos.get("entryScore")),
                ),
            )

        for event in events:
            conn.execute(
                """INSERT INTO v190_crypto_shadow_events
                   (timestamp,symbol,side,price,qty,notional_usd,entry_price,entry_score,
                    opened_at,closed_at,pnl_usd,pnl_pct,reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(event.get("timestamp") or _now()),
                    str(event.get("symbol") or ""),
                    str(event.get("side") or ""),
                    _num(event.get("price")),
                    _num(event.get("qty")),
                    event.get("notionalUsd"),
                    event.get("entryPrice"),
                    event.get("entryScore"),
                    event.get("openedAt"),
                    event.get("closedAt"),
                    event.get("pnlUsd"),
                    event.get("pnlPct"),
                    str(event.get("reason") or ""),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


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
    url = "https://data.alpaca.markets/v1beta3/crypto/us/snapshots"
    with requests.get(
        url,
        headers=_headers(m),
        params={"symbols": ",".join(symbols)},
        timeout=12,
    ) as r:
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


def _refresh(m, *, wait: bool = True) -> Dict[str, Any]:
    acquired = _scan_lock.acquire(blocking=wait)
    if not acquired:
        payload = _payload()
        payload["refreshBusy"] = True
        return payload
    try:
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
            snapshots.clear()
        rows.sort(key=lambda x: (-int(bool(x.get("qualified"))), -_num(x.get("score")), x.get("symbol", "")))
        with _lock:
            _runtime["universe"] = symbols
            _runtime["scans"] = rows
            _runtime["lastRefreshAt"] = _now()
            _runtime["lastError"] = None
            _runtime["cycles"] = int(_runtime.get("cycles") or 0) + 1
        return _payload()
    finally:
        _scan_lock.release()


def _shadow_step(m) -> None:
    with _lock:
        scans = list(_runtime.get("scans") or [])
        positions = dict(_runtime.get("shadowPositions") or {})
        cash = _num(_runtime.get("shadowCashUsd"), SHADOW_START_USD)
        realised_pnl = _num(_runtime.get("shadowRealisedPnlUsd"))
        by_symbol = {str(row.get("symbol")): row for row in scans}
        new_events: List[Dict[str, Any]] = []

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
                realised_pnl += pnl
                closed_at = _now()
                new_events.append({
                    "timestamp": closed_at,
                    "symbol": symbol,
                    "side": "SELL",
                    "price": round(price, 8),
                    "qty": round(qty, 12),
                    "notionalUsd": round(_num(pos.get("notionalUsd")), 2),
                    "entryPrice": round(entry, 8),
                    "entryScore": round(_num(pos.get("entryScore")), 4),
                    "openedAt": pos.get("openedAt"),
                    "closedAt": closed_at,
                    "pnlUsd": round(pnl, 4),
                    "pnlPct": round(pnl_pct, 4),
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
                opened_at = _now()
                entry_score = _num(row.get("score"))
                positions[symbol] = {
                    "symbol": symbol,
                    "entry": price,
                    "price": price,
                    "high": price,
                    "qty": qty,
                    "notionalUsd": spend,
                    "openedAt": opened_at,
                    "pnlPct": 0.0,
                    "entryScore": entry_score,
                }
                cash -= spend
                new_events.append({
                    "timestamp": opened_at,
                    "symbol": symbol,
                    "side": "BUY",
                    "price": round(price, 8),
                    "qty": round(qty, 12),
                    "notionalUsd": round(spend, 2),
                    "entryPrice": round(price, 8),
                    "entryScore": round(entry_score, 4),
                    "openedAt": opened_at,
                    "closedAt": None,
                    "pnlUsd": None,
                    "pnlPct": None,
                    "reason": "TOP_RANKED_QUALIFIED",
                })

        _persist_shadow_state(m, positions, cash, realised_pnl, new_events)

        _runtime["shadowPositions"] = positions
        _runtime["shadowCashUsd"] = cash
        _runtime["shadowRealisedPnlUsd"] = realised_pnl
        _runtime["shadowTrades"] = (
            list(_runtime.get("shadowTrades") or []) + new_events
        )[-200:]
        evidence = dict(_runtime.get("shadowEvidence") or {})
        evidence["buyEvents"] = int(evidence.get("buyEvents") or 0) + sum(
            1 for event in new_events if event.get("side") == "BUY"
        )
        evidence["completedTrades"] = int(evidence.get("completedTrades") or 0) + sum(
            1 for event in new_events if event.get("side") == "SELL"
        )
        _runtime["shadowEvidence"] = evidence


def _payload() -> Dict[str, Any]:
    with _lock:
        scans = list(_runtime.get("scans") or [])
        positions = list((dict(_runtime.get("shadowPositions") or {})).values())
        cash = _num(_runtime.get("shadowCashUsd"))
        unrealised = 0.0
        for pos in positions:
            unrealised += (_num(pos.get("price")) - _num(pos.get("entry"))) * _num(pos.get("qty"))
        evidence = dict(_runtime.get("shadowEvidence") or {})
        completed = int(evidence.get("completedTrades") or 0)
        next_target = 20 if completed < 20 else (50 if completed < 50 else (100 if completed < 100 else None))
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
                "evidence": {
                    "buyEvents": int(evidence.get("buyEvents") or 0),
                    "completedTrades": completed,
                    "nextTarget": next_target,
                    "progress20Pct": round(min(100.0, completed / 20.0 * 100.0), 1),
                    "progress50Pct": round(min(100.0, completed / 50.0 * 100.0), 1),
                    "progress100Pct": round(min(100.0, completed / 100.0 * 100.0), 1),
                    "persistent": True,
                },
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
            _shadow_step(m)
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
    # V19 owns crypto research now. Keep the legacy live executor dormant so its
    # 5-second worker cannot duplicate crypto discovery and consume scarce RAM.
    m.V18234_CRYPTO_LIVE_ENABLED = False

    _restore_shadow_state(m)

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
        result = _refresh(m, wait=False)
        if not result.get("refreshBusy"):
            _shadow_step(m)
        return result

    if not _started:
        _started = True
        threading.Thread(target=_worker, args=(m,), daemon=True, name="v19-crypto-v2-shadow").start()

    print(
        f"{VERSION} CRYPTO CLEAN REBUILD | old_shadow=OFF old_live_executor=OFF "
        "legacy_exit_protection=OFF new_engine=SHADOW_ONLY stock_logic=UNCHANGED",
        flush=True,
    )
