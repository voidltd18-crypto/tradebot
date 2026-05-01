import os
import time
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from flask import Flask, jsonify
from flask_cors import CORS

APP_STARTED_AT = time.time()
SCAN_INTERVAL_SECONDS = int(os.getenv("SCAN_INTERVAL_SECONDS", "8"))
DEFAULT_SYMBOLS = os.getenv("SYMBOLS", "AAPL,MSFT,NVDA,AMD,TSLA,META,AMZN,GOOGL,INTC").split(",")

ALPACA_KEY = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
ALPACA_SECRET = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
ALPACA_PAPER = os.getenv("ALPACA_PAPER", "true").lower() != "false"
ALPACA_BASE_URL = os.getenv(
    "ALPACA_BASE_URL",
    "https://paper-api.alpaca.markets" if ALPACA_PAPER else "https://api.alpaca.markets",
).rstrip("/")
DATA_BASE_URL = os.getenv("ALPACA_DATA_BASE_URL", "https://data.alpaca.markets").rstrip("/")

app = Flask(__name__)
CORS(app)
VERSION = "2026.05.01-flask-rebuild"

_state_lock = threading.Lock()
_state: Dict[str, Any] = {
    "running": False,
    "last_scan_at": None,
    "last_result": None,
    "scan_count": 0,
    "errors": [],
}

_thread_started = False


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def alpaca_headers() -> Dict[str, str]:
    if not ALPACA_KEY or not ALPACA_SECRET:
        return {}
    return {
        "APCA-API-KEY-ID": ALPACA_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET,
    }


def alpaca_get(path: str, *, data: bool = False, params: Optional[dict] = None) -> Dict[str, Any]:
    headers = alpaca_headers()
    if not headers:
        raise RuntimeError("Missing Alpaca env vars: ALPACA_API_KEY/APCA_API_KEY_ID and ALPACA_SECRET_KEY/APCA_API_SECRET_KEY")
    base = DATA_BASE_URL if data else ALPACA_BASE_URL
    response = requests.get(f"{base}{path}", headers=headers, params=params, timeout=12)
    response.raise_for_status()
    return response.json()


def market_status_payload() -> Dict[str, Any]:
    try:
        clock = alpaca_get("/v2/clock")
        return {
            "ok": True,
            "source": "alpaca",
            "is_open": bool(clock.get("is_open")),
            "status": "OPEN" if clock.get("is_open") else "CLOSED",
            "timestamp": clock.get("timestamp"),
            "next_open": clock.get("next_open"),
            "next_close": clock.get("next_close"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "source": "fallback",
            "is_open": False,
            "status": "UNKNOWN",
            "error": str(exc),
            "timestamp": now_iso(),
        }


def get_latest_trade_price(symbol: str) -> Optional[float]:
    try:
        data = alpaca_get(f"/v2/stocks/{symbol}/trades/latest", data=True)
        trade = data.get("trade") or {}
        price = trade.get("p")
        return float(price) if price is not None else None
    except Exception:
        return None


def score_symbol(symbol: str) -> Dict[str, Any]:
    price = get_latest_trade_price(symbol)
    quality = 0.50 if price else 0.0
    confidence = 0.55 if price else 0.0
    return {
        "symbol": symbol.strip().upper(),
        "price": price,
        "quality": quality,
        "confidence": confidence,
        "sniper": confidence >= 0.70,
        "action": "WATCH" if price else "NO_DATA",
        "reason": "Live Alpaca price available" if price else "No price data returned",
    }


def run_scan() -> Dict[str, Any]:
    symbols = [s.strip().upper() for s in DEFAULT_SYMBOLS if s.strip()]
    results = [score_symbol(s) for s in symbols]
    ranked = sorted(results, key=lambda x: (x["confidence"], x["quality"]), reverse=True)
    payload = {
        "ok": True,
        "mode": "realtime-safe-flask-rebuild",
        "scanned_at": now_iso(),
        "symbols_scanned": len(symbols),
        "top": ranked[:12],
        "message": "Scan complete. Safe rebuild: watches/signals only and does not place trades automatically.",
    }
    with _state_lock:
        _state["last_scan_at"] = payload["scanned_at"]
        _state["last_result"] = payload
        _state["scan_count"] += 1
    return payload


def scan_age_seconds() -> Optional[int]:
    last_at = _state.get("last_scan_at")
    if not last_at:
        return None
    try:
        return max(0, int(datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(last_at).timestamp()))
    except Exception:
        return None


def background_loop() -> None:
    with _state_lock:
        _state["running"] = True
    print("REALTIME_BACKGROUND_THREAD_STARTED", flush=True)
    while True:
        try:
            run_scan()
        except Exception as exc:
            with _state_lock:
                _state["errors"] = (_state.get("errors") or [])[-20:] + [{"at": now_iso(), "error": str(exc)}]
            print(f"BACKGROUND_SCAN_ERROR: {exc}", flush=True)
        time.sleep(SCAN_INTERVAL_SECONDS)


def start_background_thread_once() -> None:
    global _thread_started
    if _thread_started:
        return
    _thread_started = True
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()


@app.before_request
def before_request() -> None:
    start_background_thread_once()


@app.route("/")
def root():
    return jsonify({"ok": True, "service": "tradebot-backend", "version": VERSION})


@app.route("/status")
def status():
    with _state_lock:
        return jsonify({
            "ok": True,
            "backend": "online",
            "uptime_seconds": int(time.time() - APP_STARTED_AT),
            "realtime_running": _state.get("running"),
            "last_scan_at": _state.get("last_scan_at"),
            "last_scan_age_seconds": scan_age_seconds(),
            "scan_count": _state.get("scan_count", 0),
            "alpaca_configured": bool(ALPACA_KEY and ALPACA_SECRET),
        })


@app.route("/market-status")
def market_status():
    return jsonify(market_status_payload())


@app.route("/realtime-status")
def realtime_status():
    with _state_lock:
        return jsonify({
            "ok": True,
            "running": _state.get("running"),
            "scan_interval_seconds": SCAN_INTERVAL_SECONDS,
            "last_scan_at": _state.get("last_scan_at"),
            "last_scan_age_seconds": scan_age_seconds(),
            "scan_count": _state.get("scan_count", 0),
            "last_result": _state.get("last_result"),
            "errors": _state.get("errors", []),
        })


@app.route("/scan", methods=["GET", "POST"])
def scan():
    return jsonify(run_scan())


@app.route("/weekly-universe")
def weekly_universe():
    symbols = [s.strip().upper() for s in DEFAULT_SYMBOLS if s.strip()]
    return jsonify({
        "ok": True,
        "universe": symbols[:12],
        "source": "SYMBOLS env var / clean rebuild default list",
        "updated_at": now_iso(),
    })


@app.route("/account")
def account():
    try:
        account_data = alpaca_get("/v2/account")
        keep = ["status", "currency", "buying_power", "cash", "portfolio_value", "pattern_day_trader", "trading_blocked"]
        return jsonify({"ok": True, "account": {k: account_data.get(k) for k in keep}})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


if __name__ == "__main__":
    start_background_thread_once()
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
