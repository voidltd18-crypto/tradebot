import os
import time
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

app = FastAPI(title="Tradebot Backend", version="2026.05.01-clean-rebuild")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_state_lock = threading.Lock()
_state: Dict[str, Any] = {
    "running": False,
    "last_scan_at": None,
    "last_scan_age_seconds": None,
    "last_result": None,
    "scan_count": 0,
    "errors": [],
}


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
    # Stable placeholder signal: deploy-safe and explainable until full strategy is restored.
    quality = 0.50 if price else 0.0
    confidence = 0.55 if price else 0.0
    action = "WATCH" if price else "NO_DATA"
    return {
        "symbol": symbol.strip().upper(),
        "price": price,
        "quality": quality,
        "confidence": confidence,
        "sniper": confidence >= 0.70,
        "action": action,
        "reason": "Live Alpaca price available" if price else "No price data returned",
    }


def run_scan() -> Dict[str, Any]:
    symbols = [s.strip().upper() for s in DEFAULT_SYMBOLS if s.strip()]
    results = [score_symbol(s) for s in symbols]
    ranked = sorted(results, key=lambda x: (x["confidence"], x["quality"]), reverse=True)
    payload = {
        "ok": True,
        "mode": "realtime-safe-rebuild",
        "scanned_at": now_iso(),
        "symbols_scanned": len(symbols),
        "top": ranked[:12],
        "message": "Scan complete. This rebuild is safe: it watches/signals but does not place trades automatically.",
    }
    with _state_lock:
        _state["last_scan_at"] = payload["scanned_at"]
        _state["last_result"] = payload
        _state["scan_count"] += 1
        _state["last_scan_age_seconds"] = 0
    return payload


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


@app.on_event("startup")
def startup() -> None:
    thread = threading.Thread(target=background_loop, daemon=True)
    thread.start()


@app.get("/")
def root() -> Dict[str, Any]:
    return {"ok": True, "service": "tradebot-backend", "version": app.version}


@app.get("/status")
def status() -> Dict[str, Any]:
    with _state_lock:
        last_at = _state.get("last_scan_at")
        age = None
        if last_at:
            try:
                age = max(0, int(datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(last_at).timestamp()))
            except Exception:
                age = None
        return {
            "ok": True,
            "backend": "online",
            "uptime_seconds": int(time.time() - APP_STARTED_AT),
            "realtime_running": _state.get("running"),
            "last_scan_at": last_at,
            "last_scan_age_seconds": age,
            "scan_count": _state.get("scan_count", 0),
            "alpaca_configured": bool(ALPACA_KEY and ALPACA_SECRET),
        }


@app.get("/market-status")
def market_status() -> Dict[str, Any]:
    return market_status_payload()


@app.get("/realtime-status")
def realtime_status() -> Dict[str, Any]:
    with _state_lock:
        last_at = _state.get("last_scan_at")
        age = None
        if last_at:
            try:
                age = max(0, int(datetime.now(timezone.utc).timestamp() - datetime.fromisoformat(last_at).timestamp()))
            except Exception:
                age = None
        return {
            "ok": True,
            "running": _state.get("running"),
            "scan_interval_seconds": SCAN_INTERVAL_SECONDS,
            "last_scan_at": last_at,
            "last_scan_age_seconds": age,
            "scan_count": _state.get("scan_count", 0),
            "last_result": _state.get("last_result"),
            "errors": _state.get("errors", []),
        }


@app.post("/scan")
@app.get("/scan")
def scan() -> Dict[str, Any]:
    return run_scan()


@app.get("/weekly-universe")
def weekly_universe() -> Dict[str, Any]:
    symbols = [s.strip().upper() for s in DEFAULT_SYMBOLS if s.strip()]
    return {
        "ok": True,
        "universe": symbols[:12],
        "source": "SYMBOLS env var / clean rebuild default list",
        "updated_at": now_iso(),
    }


@app.get("/account")
def account() -> Dict[str, Any]:
    try:
        account = alpaca_get("/v2/account")
        keep = ["status", "currency", "buying_power", "cash", "portfolio_value", "pattern_day_trader", "trading_blocked"]
        return {"ok": True, "account": {k: account.get(k) for k in keep}}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
