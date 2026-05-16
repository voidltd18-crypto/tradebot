import os
import secrets
MAX_TRADING_CAPITAL = float(os.getenv("MAX_TRADING_CAPITAL", "200") or 200)

import sqlite3
import json
import time
import math
import re
import threading
from datetime import datetime, UTC, timedelta
from typing import Dict, Any, List, Optional

import requests
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest


# ============================================================
# REBUILT SNIPER PROFIT TRADING BOT
# ============================================================
# Includes:
# - API key protection for trading endpoints
# - Market status
# - Custom buy
# - Strict sell-then-lock protection
# - Sell reliability quantity flooring
# - Alpaca/PDT rejection logging
# - PDT-aware safer mode
# - Sniper entries
# - Confidence-based sizing
# - Stock memory
# - Persistent trade timeline
# ============================================================


# =========================
# ENV
# =========================
API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY") or os.getenv("ADMIN_PASSWORD") or os.getenv("API_ACCESS_KEY") or ""

PAPER = os.getenv("PAPER", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# GBP dashboard conversion
FX_ENABLED = True
FX_BASE = "USD"
FX_QUOTE = "GBP"
FX_FALLBACK_USD_TO_GBP = 0.78
FX_REFRESH_SECONDS = 60 * 30


if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing APCA_API_KEY_ID or APCA_API_SECRET_KEY")


# =========================
# CORE CONFIG
# =========================
BOT_NAME = "Rebuilt Sniper Profit Bot"

SAFE_UNIVERSE = [
    "NVDA", "AMD", "MSFT", "AAPL", "META",
    "AMZN", "GOOGL", "GOOG", "AVGO", "NFLX",
    "TSLA", "PLTR", "UBER", "QQQ", "SMH",
]

CHECK_INTERVAL = 60
UNIVERSE_REFRESH_SECONDS = 60 * 30

MAX_POSITIONS = 6
MAX_NEW_BUYS_PER_LOOP = 1
MAX_POSITION_VALUE_PCT = 0.12
TARGET_POSITION_VALUE_PCT = 0.08
MIN_ORDER_NOTIONAL = 1.00
CASH_BUFFER = 0.50

MAX_SPREAD = 0.015
PREFER_SPREAD_UNDER = 0.006

BUY_DIP = 0.9985
MIN_PULLBACK = 0.0010
MAX_PULLBACK = 0.0450
MIN_TICKS_BEFORE_BUY = 3
MOMENTUM_LOOKBACK_POINTS = 5
MIN_SHORT_MOMENTUM = -0.015
MAX_SHORT_MOMENTUM = 0.045

STOP_LOSS = 0.982
TRAIL_START = 1.012
TRAIL_GIVEBACK = 0.993

MAX_DAILY_LOSS = -8.00
MAX_TRADES_PER_DAY = 12
DUST_THRESHOLD = 0.1

STRICT_ONE_CYCLE_PER_STOCK_PER_DAY = True
ALLOW_CUSTOM_BUY = True
CUSTOM_BUY_REQUIRES_MARKET_OPEN = True
ENABLE_MANUAL_BUTTONS = True
MANAGE_OUTSIDE_UNIVERSE_POSITIONS = False


# =========================
# PROFIT / PDT / MEMORY
# =========================
PROFIT_MODE_ENABLED = True
ROTATION_MODE_ENABLED = True
ROTATION_MIN_QUALITY_EDGE = 0.018
ROTATE_ONLY_IF_WEAKEST_PNL_BELOW = 0.35
ROTATION_COOLDOWN_SECONDS = 60 * 20

PDT_AWARE_MODE_ENABLED = True
AVOID_SAME_DAY_PROFIT_SELLS = True
AVOID_SAME_DAY_ROTATION_SELLS = True
MIN_HOLD_MINUTES_BEFORE_PROFIT_SELL = 45
MIN_HOLD_MINUTES_BEFORE_ROTATION = 60
HARD_STOP_LOSS_PCT = -3.50
MAX_NEW_BUYS_PER_DAY_PDT_AWARE = 6

# Faster Exit / Partial Profit Mode
FAST_EXIT_MODE_ENABLED = True
PARTIAL_PROFIT_ENABLED = True
PARTIAL_PROFIT_TRIGGER_PCT = 1.00
PARTIAL_PROFIT_SELL_PCT = 0.50
POST_PARTIAL_TRAIL_GIVEBACK = 0.996
FAST_STOP_LOSS_PCT = -1.20
STALL_EXIT_ENABLED = True
STALL_EXIT_AFTER_MINUTES = 90
STALL_EXIT_MIN_PNL_PCT = 0.30
MIN_SELL_NOTIONAL = 1.00

# Profit Optimiser / Analytics / Auto-Improve
PROFIT_OPTIMIZER_ENABLED = True
ANALYTICS_ENABLED = True
AUTO_IMPROVE_ENABLED = True

DAILY_PROFIT_TARGET = 4.00
DAILY_LOSS_LIMIT_OPTIMIZER = -4.00
PAUSE_BUYS_AFTER_DAILY_TARGET = True
PAUSE_BUYS_AFTER_DAILY_LOSS = True

OPTIMIZED_STOP_LOSS = 0.985
OPTIMIZED_TRAIL_START = 1.020
OPTIMIZED_TRAIL_GIVEBACK = 0.995
OPTIMIZED_FAST_STOP_LOSS_PCT = -1.00
OPTIMIZED_PARTIAL_PROFIT_TRIGGER_PCT = 1.20
OPTIMIZED_PARTIAL_PROFIT_SELL_PCT = 0.35

AUTO_BLACKLIST_ENABLED = True
AUTO_BLACKLIST_MIN_TRADES = 4
AUTO_BLACKLIST_MAX_WINRATE = 0.38
AUTO_BLACKLIST_MAX_TOTAL_PNL = -1.50
AUTO_BOOST_ENABLED = True
AUTO_BOOST_MIN_TRADES = 4
AUTO_BOOST_MIN_WINRATE = 0.60
AUTO_BOOST_MIN_TOTAL_PNL = 1.00
AUTO_BOOST_MULTIPLIER = 1.20
AUTO_REDUCE_MULTIPLIER = 0.70
OPTIMIZER_MIN_CONFIDENCE = 0.68



SNIPER_MODE_ENABLED = True
CONFIDENCE_SIZING_ENABLED = True
STOCK_MEMORY_ENABLED = True
TRADE_TIMELINE_ENABLED = True

SNIPER_MIN_CONFIDENCE = 0.58
SNIPER_MIN_QUALITY = 0.020
SNIPER_MAX_SPREAD = 0.012
SNIPER_MIN_PULLBACK = 0.0015
SNIPER_MAX_PULLBACK = 0.035
SNIPER_MIN_MOMENTUM = -0.003

# A+ trade quality gate
A_PLUS_GATE_ENABLED = True
A_PLUS_MIN_CONFIDENCE = 0.70
A_PLUS_MIN_QUALITY = 0.026
A_PLUS_MAX_SPREAD = 0.010
A_PLUS_REQUIRE_NON_NEGATIVE_MOMENTUM = True
A_PLUS_BLOCK_LOW_CONFIDENCE_MANUAL_BUY = True

# Temporary loser blacklist
LOSER_BLACKLIST_ENABLED = True
LOSER_BLACKLIST_LOSS_STREAK = 2
LOSER_BLACKLIST_MIN_TRADES = 3
LOSER_BLACKLIST_HOURS = 24
TEMP_BLACKLIST_FILE = "temp_blacklist.json"

LOW_CONFIDENCE_SIZE_MULTIPLIER = 0.65
MEDIUM_CONFIDENCE_SIZE_MULTIPLIER = 1.00
HIGH_CONFIDENCE_SIZE_MULTIPLIER = 1.35
MAX_CONFIDENCE_POSITION_VALUE_PCT = 0.14

MEMORY_MIN_TRADES_FOR_TRUST = 3
MEMORY_BAD_WINRATE = 0.35
MEMORY_GOOD_WINRATE = 0.58
MEMORY_BAD_MULTIPLIER = 0.70
MEMORY_GOOD_MULTIPLIER = 1.15


# SQLite persistent trade memory
SQLITE_ENABLED = True
SQLITE_DB_FILE = os.getenv("SQLITE_DB_FILE", "trades.db")
BACKFILL_ORDER_LIMIT = 500
BACKFILL_CHUNK_SIZE = 500
BACKFILL_MAX_PAGES = 50

TRADE_HISTORY_FILE = "trade_history.json"
STOCK_MEMORY_FILE = "stock_memory.json"



if PROFIT_OPTIMIZER_ENABLED:
    STOP_LOSS = OPTIMIZED_STOP_LOSS
    TRAIL_START = OPTIMIZED_TRAIL_START
    TRAIL_GIVEBACK = OPTIMIZED_TRAIL_GIVEBACK
    FAST_STOP_LOSS_PCT = OPTIMIZED_FAST_STOP_LOSS_PCT
    PARTIAL_PROFIT_TRIGGER_PCT = OPTIMIZED_PARTIAL_PROFIT_TRIGGER_PCT
    PARTIAL_PROFIT_SELL_PCT = OPTIMIZED_PARTIAL_PROFIT_SELL_PCT


# Weekly Auto Universe Rotation
AUTO_UNIVERSE_ENABLED = True
AUTO_UNIVERSE_SIZE = 12
AUTO_UNIVERSE_REFRESH_DAY = 0
AUTO_UNIVERSE_MIN_HOURS_BETWEEN_REFRESH = 12
AUTO_UNIVERSE_KEEP_WINNERS = True
AUTO_UNIVERSE_KEEP_WINNER_MIN_PNL = 0.50
AUTO_UNIVERSE_KEEP_WINNER_MIN_WINRATE = 0.55
AUTO_UNIVERSE_REMOVE_LOSER_MAX_WINRATE = 0.35
AUTO_UNIVERSE_REMOVE_LOSER_MAX_PNL = -1.00
AUTO_UNIVERSE_MIN_PRICE = 1.00
AUTO_UNIVERSE_MAX_PRICE = 800.00
AUTO_UNIVERSE_MAX_SPREAD = 0.020
AUTO_UNIVERSE_CANDIDATE_POOL = [
    "NVDA", "AMD", "MSFT", "AAPL", "META",
    "AMZN", "GOOGL", "GOOG", "AVGO", "NFLX",
    "TSLA", "PLTR", "UBER", "QQQ", "SMH",
]

# =========================
# CLIENTS
# =========================
trading_client = TradingClient(API_KEY, API_SECRET, paper=PAPER)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)


# =========================
# STATE
# =========================
current_universe = list(dict.fromkeys(SAFE_UNIVERSE))
state: Dict[str, Dict[str, Any]] = {}

for symbol in current_universe:
    state[symbol] = {
        "ref": None,
        "highest_since_entry": None,
        "price_curve": [],
        "custom": False,
    }

locked_today: Dict[str, str] = {}
custom_symbols: Dict[str, bool] = {}
last_universe_refresh_ts = 0

latest_status: Dict[str, Any] = {}
latest_scans: List[Dict[str, Any]] = []

trade_events: List[Dict[str, Any]] = []
trade_history: List[Dict[str, Any]] = []
stock_memory: Dict[str, Dict[str, Any]] = {}
temp_blacklist: Dict[str, Any] = {}
alpaca_rejection_events: List[Dict[str, Any]] = []
pdt_warning_events: List[Dict[str, Any]] = []
partial_profit_taken: Dict[str, str] = {}
equity_curve: List[Dict[str, Any]] = []

bot_enabled = True
manual_override = False
emergency_stop = False
bot_thread_started = False
bot_lock = threading.Lock()

starting_equity_today: Optional[float] = None
starting_equity_day: Optional[str] = None
last_rotation_ts = 0
fx_cache: Dict[str, Any] = {"rate": FX_FALLBACK_USD_TO_GBP, "updated": 0, "source": "fallback"}


# =========================
# APP
# =========================
app = FastAPI(title="Rebuilt Sniper Profit Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# SECURITY
# =========================
def verify_api_key(request: Request):
    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=500, detail="Dashboard API key not configured")

    key = request.headers.get("x-api-key")
    if key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


@app.post("/login")
def login(payload: dict = Body(...)):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))

    admin_username = os.getenv("ADMIN_USERNAME", "admin")
    admin_password = os.getenv("ADMIN_PASSWORD", DASHBOARD_API_KEY)

    if not admin_password:
        raise HTTPException(status_code=503, detail="Admin password not configured")

    if not secrets.compare_digest(username, admin_username) or not secrets.compare_digest(password, admin_password):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Existing protected endpoints already expect x-api-key, so return that as the session token.
    return {"ok": True, "token": DASHBOARD_API_KEY or admin_password, "username": username}


@app.get("/auth-check")
def auth_check(request: Request):
    verify_api_key(request)
    return {"ok": True, "authenticated": True}

# =========================
# UTIL
# =========================
def today_str():
    return datetime.now(UTC).strftime("%Y-%m-%d")


def now_time():
    return datetime.now(UTC).strftime("%H:%M:%S")


def now_chart_time():
    return datetime.now(UTC).strftime("%H:%M")


def notify(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=5,
        )
    except Exception:
        pass


def safe_load_json(path: str, fallback):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return fallback


def safe_save_json(path: str, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"SAVE ERROR {path}: {e}")


def load_persistent_state():
    global trade_history, stock_memory, temp_blacklist
    trade_history = safe_load_json(TRADE_HISTORY_FILE, [])
    stock_memory = safe_load_json(STOCK_MEMORY_FILE, {})
    temp_blacklist = safe_load_json(TEMP_BLACKLIST_FILE, {})


def save_trade_history():
    safe_save_json(TRADE_HISTORY_FILE, trade_history[-2000:])


def save_stock_memory():
    safe_save_json(STOCK_MEMORY_FILE, stock_memory)


def save_temp_blacklist():
    safe_save_json(TEMP_BLACKLIST_FILE, temp_blacklist)


def cleanup_temp_blacklist():
    now = datetime.now(UTC)
    changed = False

    for symbol, data in list(temp_blacklist.items()):
        try:
            until = datetime.fromisoformat(data.get("until", ""))
            if until <= now:
                del temp_blacklist[symbol]
                changed = True
        except Exception:
            del temp_blacklist[symbol]
            changed = True

    if changed:
        save_temp_blacklist()


def is_temp_blacklisted(symbol: str):
    if not LOSER_BLACKLIST_ENABLED:
        return False, ""

    cleanup_temp_blacklist()
    data = temp_blacklist.get(symbol.upper())

    if not data:
        return False, ""

    return True, data.get("reason", "temporarily blacklisted")


def add_temp_blacklist(symbol: str, reason: str):
    if not LOSER_BLACKLIST_ENABLED:
        return

    until = datetime.now(UTC) + timedelta(hours=LOSER_BLACKLIST_HOURS)
    temp_blacklist[symbol.upper()] = {
        "reason": reason,
        "until": until.isoformat(),
    }
    save_temp_blacklist()
    print(f"BLACKLIST | {symbol} | {reason} until {until.isoformat()}")


def current_loss_streak(symbol: str):
    streak = 0
    for event in reversed(trade_history):
        if event.get("symbol") != symbol or event.get("side") != "SELL":
            continue
        if float(event.get("pnl", 0.0)) < 0:
            streak += 1
        else:
            break
    return streak


def refresh_blacklist_from_memory(symbol: str):
    if not LOSER_BLACKLIST_ENABLED:
        return

    m = get_memory(symbol)

    if m.get("trades", 0) < LOSER_BLACKLIST_MIN_TRADES:
        return

    streak = current_loss_streak(symbol)

    if streak >= LOSER_BLACKLIST_LOSS_STREAK:
        add_temp_blacklist(symbol, f"{streak} loss streak")


def a_plus_gate(scan: Dict[str, Any]):
    if not A_PLUS_GATE_ENABLED:
        return True, "A+ gate off"

    symbol = scan.get("symbol", "")
    blacklisted, reason = is_temp_blacklisted(symbol)
    if blacklisted:
        return False, f"blacklisted: {reason}"

    confidence = float(scan.get("confidence", 0.0))
    quality = float(scan.get("quality_score", scan.get("qualityScore", 0.0)))
    spread = float(scan.get("spread", 1.0))
    momentum = float(scan.get("short_momentum", scan.get("shortMomentum", 0.0)))

    if confidence < A_PLUS_MIN_CONFIDENCE:
        return False, f"confidence {confidence:.2f} below A+ {A_PLUS_MIN_CONFIDENCE:.2f}"

    if quality < A_PLUS_MIN_QUALITY:
        return False, f"quality {quality:.4f} below A+ {A_PLUS_MIN_QUALITY:.4f}"

    if spread > A_PLUS_MAX_SPREAD:
        return False, f"spread {spread:.4f} above A+ {A_PLUS_MAX_SPREAD:.4f}"

    if A_PLUS_REQUIRE_NON_NEGATIVE_MOMENTUM and momentum < 0:
        return False, f"momentum negative {momentum:.4f}"

    return True, "A+ PASS"



def ensure_symbol_state(symbol: str, custom=False):
    symbol = symbol.upper()
    if symbol not in state:
        state[symbol] = {
            "ref": None,
            "highest_since_entry": None,
            "price_curve": [],
            "custom": custom,
        }
    if custom:
        state[symbol]["custom"] = True


def add_symbol_to_universe(symbol: str, custom=False):
    symbol = symbol.upper().strip()
    if symbol not in current_universe:
        current_universe.append(symbol)
    ensure_symbol_state(symbol, custom=custom)
    if custom:
        custom_symbols[symbol] = True


def reset_daily_flags_if_needed():
    global starting_equity_today, starting_equity_day

    today = today_str()
    for symbol, day in list(locked_today.items()):
        if day != today:
            del locked_today[symbol]

    for symbol, day in list(partial_profit_taken.items()):
        if day != today:
            del partial_profit_taken[symbol]

    if starting_equity_day != today:
        try:
            account = get_account()
            starting_equity_today = float(account.equity)
            starting_equity_day = today
            trade_events.clear()
            alpaca_rejection_events.clear()
            pdt_warning_events.clear()
            equity_curve.clear()
        except Exception:
            pass


def lock_symbol_until_tomorrow(symbol: str):
    if STRICT_ONE_CYCLE_PER_STOCK_PER_DAY:
        locked_today[symbol] = today_str()


def is_locked_today(symbol: str):
    return locked_today.get(symbol) == today_str()


def floor_qty(qty: float, decimals: int = 6):
    factor = 10 ** decimals
    return max(0.0, int(float(qty) * factor) / factor)


def parse_available_qty(error_text: str):
    try:
        m = re.search(r"available[:=]\s*([0-9]*\.?[0-9]+)", str(error_text), re.IGNORECASE)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def is_insufficient_qty_error(error_text: str):
    lower = str(error_text).lower()
    return "insufficient qty" in lower or "insufficient quantity" in lower


def is_likely_pdt_error(error_text: str):
    lower = str(error_text).lower()
    return any(term in lower for term in ["pattern day", "pdt", "day trade", "day-trade", "day trading"])



# =========================
# FX / GBP CONVERSION
# =========================
def get_usd_to_gbp_rate():
    global fx_cache

    if not FX_ENABLED:
        return FX_FALLBACK_USD_TO_GBP

    now = time.time()

    if fx_cache.get("rate") and (now - float(fx_cache.get("updated", 0))) < FX_REFRESH_SECONDS:
        return float(fx_cache["rate"])

    urls = [
        "https://api.frankfurter.app/latest?from=USD&to=GBP",
        "https://api.exchangerate.host/latest?base=USD&symbols=GBP",
    ]

    for url in urls:
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            rate = float(data["rates"]["GBP"])

            if rate > 0:
                fx_cache = {
                    "rate": rate,
                    "updated": now,
                    "source": url,
                }
                return rate
        except Exception as e:
            print(f"FX ERROR {url}: {e}")

    fx_cache = {
        "rate": FX_FALLBACK_USD_TO_GBP,
        "updated": now,
        "source": "fallback",
    }
    return FX_FALLBACK_USD_TO_GBP


def money_gbp(value_usd: float):
    try:
        return float(value_usd) * get_usd_to_gbp_rate()
    except Exception:
        return 0.0


def fx_payload():
    rate = get_usd_to_gbp_rate()
    return {
        "enabled": FX_ENABLED,
        "base": FX_BASE,
        "quote": FX_QUOTE,
        "usdToGbp": rate,
        "label": "USD/GBP",
        "source": fx_cache.get("source", "fallback"),
        "updated": fx_cache.get("updated", 0),
    }


# =========================
# ACCOUNT / MARKET
# =========================
def get_account():
    return trading_client.get_account()


def get_equity():
    return float(get_account().equity)


def get_market_status_payload():
    try:
        clock = trading_client.get_clock()
        return {
            "isOpen": bool(clock.is_open),
            "timestamp": str(clock.timestamp),
            "nextOpen": str(clock.next_open),
            "nextClose": str(clock.next_close),
            "label": "OPEN" if clock.is_open else "CLOSED",
        }
    except Exception as e:
        return {"isOpen": False, "label": "UNKNOWN", "error": str(e), "timestamp": "", "nextOpen": "", "nextClose": ""}


def get_quote(symbol: str):
    req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    quote = data_client.get_stock_latest_quote(req)[symbol]
    bid = quote.bid_price
    ask = quote.ask_price
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        raise ValueError(f"Bad quote for {symbol}")
    mid = (bid + ask) / 2.0
    spread = (ask - bid) / mid
    return {"bid": float(bid), "ask": float(ask), "mid": float(mid), "spread": float(spread)}


def get_position(symbol: str):
    try:
        pos = trading_client.get_open_position(symbol)
        return float(pos.qty), float(pos.avg_entry_price)
    except Exception:
        return 0.0, 0.0


def get_open_orders(symbol=None):
    try:
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        orders = trading_client.get_orders(filter=request)
        if symbol is None:
            return orders
        return [order for order in orders if str(order.symbol).upper() == symbol.upper()]
    except Exception:
        return []


def has_open_order(symbol: str):
    return len(get_open_orders(symbol)) > 0


def get_all_positions():
    positions = []
    try:
        raw_positions = trading_client.get_all_positions()
    except Exception:
        return positions

    for pos in raw_positions:
        try:
            symbol = str(pos.symbol).upper()
            qty = float(pos.qty)
            entry = float(pos.avg_entry_price)
            market_value = float(pos.market_value)

            if qty <= DUST_THRESHOLD:
                continue

            ensure_symbol_state(symbol)

            quote_price = 0.0
            spread = 0.0
            try:
                quote = get_quote(symbol)
                quote_price = quote["mid"]
                spread = quote["spread"]
            except Exception:
                try:
                    quote_price = float(pos.current_price)
                except Exception:
                    quote_price = 0.0

            pnl = 0.0
            pnl_pct = 0.0
            if entry > 0 and quote_price > 0:
                pnl = (quote_price - entry) * qty
                pnl_pct = ((quote_price / entry) - 1.0) * 100.0

            highest = state[symbol].get("highest_since_entry")
            if quote_price > 0 and (highest is None or quote_price > highest):
                state[symbol]["highest_since_entry"] = quote_price

            trail_start_price = entry * TRAIL_START if entry > 0 else 0.0
            trail_floor = (state[symbol].get("highest_since_entry") or 0.0) * TRAIL_GIVEBACK
            trailing_active = quote_price >= trail_start_price if quote_price > 0 and trail_start_price > 0 else False

            positions.append({
                "symbol": symbol,
                "qty": qty,
                "entry": entry,
                "price": quote_price,
                "marketValue": market_value,
                "marketValueGbp": money_gbp(market_value),
                "pnl": pnl,
                "pnlGbp": money_gbp(pnl),
                "pnlPct": pnl_pct,
                "spread": spread,
                "highest": state[symbol].get("highest_since_entry") or 0.0,
                "trailStartPrice": trail_start_price,
                "trailFloor": trail_floor,
                "trailingActive": trailing_active,
                "inUniverse": symbol in current_universe,
                "custom": bool(state.get(symbol, {}).get("custom")),
                "lockedToday": is_locked_today(symbol),
                "boughtToday": was_bought_today(symbol),
                "minutesSinceBuy": minutes_since_today_buy(symbol),
                "partialProfitTaken": has_taken_partial_profit(symbol),
                "partialProfitTriggerPct": PARTIAL_PROFIT_TRIGGER_PCT,
                "fastStopLossPct": FAST_STOP_LOSS_PCT,
                "stallExitAfterMinutes": STALL_EXIT_AFTER_MINUTES,
            })
        except Exception:
            continue

    positions.sort(key=lambda p: abs(p.get("marketValue", 0.0)), reverse=True)
    return positions


# =========================
# HISTORY / MEMORY
# =========================
def get_today_buy_event(symbol: str):
    today = today_str()
    for event in reversed(trade_events + trade_history[-100:]):
        if event.get("symbol") == symbol and event.get("side") == "BUY" and event.get("day") == today:
            return event
    return None


def was_bought_today(symbol: str):
    return get_today_buy_event(symbol) is not None


def minutes_since_today_buy(symbol: str):
    buy = get_today_buy_event(symbol)
    if not buy:
        return 999999
    try:
        buy_time = datetime.strptime(f"{buy['day']} {buy['time']}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return max(0, int((datetime.now(UTC) - buy_time).total_seconds() / 60))
    except Exception:
        return 0


def today_buy_count():
    today = today_str()
    return len([t for t in trade_events if t.get("side") == "BUY" and t.get("day") == today])


def get_memory(symbol: str):
    symbol = symbol.upper()
    if symbol not in stock_memory:
        stock_memory[symbol] = {
            "wins": 0, "losses": 0, "trades": 0,
            "totalPnl": 0.0, "totalPnlPct": 0.0,
            "avgPnl": 0.0, "avgPnlPct": 0.0,
            "winRate": 0.0, "trust": "NEW", "lastResult": "—",
        }
    return stock_memory[symbol]


def update_stock_memory_from_sell(symbol: str, pnl: float, pnl_pct: float):
    if not STOCK_MEMORY_ENABLED:
        return
    m = get_memory(symbol)
    m["trades"] += 1
    m["totalPnl"] += float(pnl)
    m["totalPnlPct"] += float(pnl_pct)
    if pnl >= 0:
        m["wins"] += 1
        m["lastResult"] = "WIN"
    else:
        m["losses"] += 1
        m["lastResult"] = "LOSS"
    m["winRate"] = m["wins"] / max(1, m["trades"])
    m["avgPnl"] = m["totalPnl"] / max(1, m["trades"])
    m["avgPnlPct"] = m["totalPnlPct"] / max(1, m["trades"])
    if m["trades"] < MEMORY_MIN_TRADES_FOR_TRUST:
        m["trust"] = "NEW"
    elif m["winRate"] >= MEMORY_GOOD_WINRATE:
        m["trust"] = "GOOD"
    elif m["winRate"] <= MEMORY_BAD_WINRATE:
        m["trust"] = "BAD"
    else:
        m["trust"] = "NEUTRAL"
    save_stock_memory()
    refresh_blacklist_from_memory(symbol)


def memory_multiplier(symbol: str):
    if not STOCK_MEMORY_ENABLED:
        return 1.0
    m = get_memory(symbol)
    if m["trades"] < MEMORY_MIN_TRADES_FOR_TRUST:
        return 1.0
    if m["winRate"] >= MEMORY_GOOD_WINRATE:
        return MEMORY_GOOD_MULTIPLIER
    if m["winRate"] <= MEMORY_BAD_WINRATE:
        return MEMORY_BAD_MULTIPLIER
    return 1.0


def add_trade_history_event(event: Dict[str, Any]):
    if not TRADE_TIMELINE_ENABLED:
        return
    equity = 0.0
    try:
        equity = float(get_account().equity)
    except Exception:
        pass
    item = {
        **event,
        "timestamp": datetime.now(UTC).isoformat(),
        "equity": equity,
        "equityGbp": money_gbp(equity),
        "fxRate": get_usd_to_gbp_rate(),
    }

    if "pnl" in item:
        item["pnlGbp"] = money_gbp(float(item.get("pnl") or 0.0))

    if "amount" in item:
        item["amountGbp"] = money_gbp(float(item.get("amount") or 0.0))
    trade_history.append(item)
    if len(trade_history) > 2000:
        del trade_history[:-2000]
    save_trade_history()
    save_trade_to_db(item, source="bot")


def stock_memory_payload():
    items = [{"symbol": s, **m} for s, m in stock_memory.items()]
    items.sort(key=lambda x: (-x.get("winRate", 0), -x.get("trades", 0)))
    return items


# =========================
# SIGNALS
# =========================
def calculate_confidence(scan: Dict[str, Any]):
    quality = float(scan.get("quality_score", 0.0))
    spread = float(scan.get("spread", 1.0))
    momentum = float(scan.get("short_momentum", 0.0))
    pullback = float(scan.get("pullback", 0.0))
    symbol = scan.get("symbol", "")

    confidence = 0.0
    confidence += min(0.35, quality * 8.0)
    confidence += 0.20 if spread <= PREFER_SPREAD_UNDER else 0.10 if spread <= MAX_SPREAD else 0.0
    confidence += 0.20 if momentum >= 0 else 0.10 if momentum >= SNIPER_MIN_MOMENTUM else 0.0
    confidence += 0.15 if SNIPER_MIN_PULLBACK <= pullback <= SNIPER_MAX_PULLBACK else 0.0
    confidence *= memory_multiplier(symbol)
    confidence = max(0.0, min(1.0, confidence))

    label = "HIGH" if confidence >= 0.75 else "MEDIUM" if confidence >= 0.58 else "LOW"
    return confidence, label


def sniper_passes(scan: Dict[str, Any]):
    if not SNIPER_MODE_ENABLED:
        return True, "SNIPER OFF"
    confidence, label = calculate_confidence(scan)
    if confidence < SNIPER_MIN_CONFIDENCE:
        return False, f"confidence too low {confidence:.2f}"
    if scan["quality_score"] < SNIPER_MIN_QUALITY:
        return False, f"quality too low {scan['quality_score']:.4f}"
    if scan["spread"] > SNIPER_MAX_SPREAD:
        return False, f"spread too wide {scan['spread']:.4f}"
    if scan["pullback"] < SNIPER_MIN_PULLBACK or scan["pullback"] > SNIPER_MAX_PULLBACK:
        return False, f"pullback outside sniper range {scan['pullback']:.4f}"
    if scan["short_momentum"] < SNIPER_MIN_MOMENTUM:
        return False, f"momentum too weak {scan['short_momentum']:.4f}"
    return True, f"{label} confidence {confidence:.2f}"


def compute_short_momentum(symbol: str, current_price: float):
    curve = state[symbol].get("price_curve", [])
    if len(curve) < MOMENTUM_LOOKBACK_POINTS:
        return 0.0
    old = curve[-MOMENTUM_LOOKBACK_POINTS]["value"]
    return 0.0 if old <= 0 else (current_price / old) - 1.0


def compute_scan(symbol: str):
    ensure_symbol_state(symbol, custom=symbol in custom_symbols)
    quote = get_quote(symbol)
    qty, entry = get_position(symbol)

    price = quote["mid"]
    spread = quote["spread"]

    if state[symbol]["ref"] is None:
        state[symbol]["ref"] = price
    ref = state[symbol]["ref"]
    if price > ref:
        state[symbol]["ref"] = price
        ref = price

    if qty > DUST_THRESHOLD:
        highest = state[symbol].get("highest_since_entry")
        if highest is None or price > highest:
            state[symbol]["highest_since_entry"] = price
    else:
        state[symbol]["highest_since_entry"] = None

    curve = state[symbol]["price_curve"]
    curve.append({"t": now_chart_time(), "value": price})
    if len(curve) > 180:
        curve.pop(0)

    short_momentum = compute_short_momentum(symbol, price)
    pullback = max(0.0, (ref - price) / ref) if ref > 0 else 0.0
    tightness_score = max(0.0, PREFER_SPREAD_UNDER - spread)

    quality_score = 0.0
    if MIN_PULLBACK <= pullback <= MAX_PULLBACK:
        quality_score += pullback * 3.0
    if spread <= MAX_SPREAD:
        quality_score += tightness_score * 2.0
    if MIN_SHORT_MOMENTUM <= short_momentum <= MAX_SHORT_MOMENTUM:
        quality_score += max(0.0, short_momentum) * 0.7
    else:
        quality_score -= 0.02

    buy_trigger = ref * BUY_DIP
    locked = is_locked_today(symbol)
    ready_to_buy = (
        not locked and
        price <= buy_trigger and
        spread <= MAX_SPREAD and
        MIN_PULLBACK <= pullback <= MAX_PULLBACK and
        short_momentum >= MIN_SHORT_MOMENTUM and
        len(curve) >= MIN_TICKS_BEFORE_BUY
    )

    temp = {
        "symbol": symbol, "quality_score": quality_score, "spread": spread,
        "short_momentum": short_momentum, "pullback": pullback,
    }
    confidence, confidence_label = calculate_confidence(temp)
    sniper_ok, sniper_reason = sniper_passes({**temp, "ready_to_buy": ready_to_buy, "confidence": confidence})
    aplus_ok, aplus_reason = a_plus_gate({**temp, "confidence": confidence})

    return {
        "symbol": symbol,
        "price": price,
        "spread": spread,
        "bid": quote["bid"],
        "ask": quote["ask"],
        "qty": qty,
        "entry": entry,
        "ref": ref,
        "score": (price / ref) - 1.0 if ref > 0 else 0.0,
        "pullback": pullback,
        "short_momentum": short_momentum,
        "quality_score": quality_score,
        "buy_trigger": buy_trigger,
        "ready_to_buy": ready_to_buy,
        "locked_today": locked,
        "custom": symbol in custom_symbols,
        "price_curve": curve,
        "confidence": confidence,
        "confidence_label": confidence_label,
        "sniper_pass": sniper_ok,
        "sniper_reason": sniper_reason,
        "a_plus_pass": aplus_ok,
        "a_plus_reason": aplus_reason,
    }


# =========================
# ORDERS / RISK
# =========================
def get_daily_pnl():
    global starting_equity_today
    try:
        equity = get_equity()
        if starting_equity_today is None:
            starting_equity_today = equity
        return equity - starting_equity_today
    except Exception:
        return 0.0


def daily_trade_count():
    today = today_str()
    return len([t for t in trade_events if t.get("day") == today])


def risk_blocked():
    if PROFIT_OPTIMIZER_ENABLED:
        opt_blocked, opt_reason = profit_guardrail_status()
        if opt_blocked:
            return True, opt_reason

    pnl = get_daily_pnl()
    if pnl <= MAX_DAILY_LOSS:
        return True, f"Max daily loss hit: {pnl:.2f}"
    if daily_trade_count() >= MAX_TRADES_PER_DAY:
        return True, "Max trades per day reached"
    return False, ""


def allowed_new_position_count():
    return max(0, MAX_POSITIONS - len(get_all_positions()))


def calculate_new_position_notional():
    account = get_account()
    equity = float(account.equity)
    buying_power = float(account.buying_power)

    # Profit banking cap now controls sizing. If account equity grows above
    # the saved cap, new trade sizes are calculated from the capped amount,
    # not full account equity.
    sizing_equity = effective_trading_equity(equity) if "effective_trading_equity" in globals() else equity

    target_value = sizing_equity * TARGET_POSITION_VALUE_PCT
    max_value = sizing_equity * MAX_POSITION_VALUE_PCT
    usable_cash = max(0.0, buying_power - CASH_BUFFER)
    return round(max(0.0, min(target_value, max_value, usable_cash)), 2)


def confidence_notional(scan):
    base = calculate_new_position_notional()
    if not CONFIDENCE_SIZING_ENABLED:
        return base
    confidence, label = calculate_confidence(scan)
    mult = HIGH_CONFIDENCE_SIZE_MULTIPLIER if label == "HIGH" else MEDIUM_CONFIDENCE_SIZE_MULTIPLIER if label == "MEDIUM" else LOW_CONFIDENCE_SIZE_MULTIPLIER
    try:
        account_equity = float(get_account().equity)
        sizing_equity = effective_trading_equity(account_equity) if "effective_trading_equity" in globals() else account_equity
    except Exception:
        sizing_equity = 0.0
    cap = sizing_equity * MAX_CONFIDENCE_POSITION_VALUE_PCT if sizing_equity > 0 else base
    return round(max(0.0, min(base * mult, cap)), 2)


def can_buy_symbol(symbol: str):
    if STRICT_ONE_CYCLE_PER_STOCK_PER_DAY and is_locked_today(symbol):
        return False, f"{symbol} locked until tomorrow"
    if has_open_order(symbol):
        return False, f"{symbol} existing open order"
    qty, _ = get_position(symbol)
    if qty > DUST_THRESHOLD:
        return False, f"{symbol} already holding"
    return True, ""


def add_alpaca_rejection_event(symbol: str, reason: str, error_text: str):
    label = "PDT BLOCK" if is_likely_pdt_error(error_text) else "ALPACA SELL REJECTED"
    event = {
        "day": today_str(), "time": now_time(), "symbol": symbol,
        "type": label, "reason": reason,
        "message": f"{label} | {symbol} sell was rejected by Alpaca.",
        "error": str(error_text),
    }
    alpaca_rejection_events.append(event)
    if len(alpaca_rejection_events) > 100:
        alpaca_rejection_events.pop(0)
    print(f"{event['message']} | {event['error']}")
    notify(f"⚠️ {event['message']} Reason: {event['error']}")


def add_pdt_warning(symbol: str, reason: str):
    event = {"day": today_str(), "time": now_time(), "symbol": symbol, "reason": reason, "message": f"PDT AWARE | {symbol}: {reason}"}
    pdt_warning_events.append(event)
    if len(pdt_warning_events) > 100:
        pdt_warning_events.pop(0)
    print(event["message"])


def pdt_aware_should_avoid_sell(symbol: str, reason: str, pnl_pct: float, allow_hard_stop=False):
    if not PDT_AWARE_MODE_ENABLED or not was_bought_today(symbol):
        return False
    if allow_hard_stop and pnl_pct <= HARD_STOP_LOSS_PCT:
        add_pdt_warning(symbol, f"hard stop override: attempting sell despite same-day buy, pnl={pnl_pct:.2f}%")
        return False
    mins = minutes_since_today_buy(symbol)
    if "ROTATE" in reason.upper() and AVOID_SAME_DAY_ROTATION_SELLS:
        add_pdt_warning(symbol, f"rotation skipped because bought today; hold until next day reset")
        return True
    if ("TRAILING" in reason.upper() or "PROFIT" in reason.upper()) and AVOID_SAME_DAY_PROFIT_SELLS:
        add_pdt_warning(symbol, f"profit sell skipped because bought today; hold until next day reset")
        return True
    return False


def market_buy_notional(symbol: str, notional_amount: float, reason="AUTO BUY"):
    order = MarketOrderRequest(symbol=symbol, notional=round(notional_amount, 2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
    trading_client.submit_order(order)
    event = {
        "day": today_str(),
        "time": now_time(),
        "side": "BUY",
        "symbol": symbol,
        "amount": round(notional_amount, 2),
        "amountGbp": round(money_gbp(notional_amount), 2),
        "reason": reason,
        "pnl": 0.0,
        "pnlGbp": 0.0,
    }
    trade_events.append(event)
    add_trade_history_event(event)
    notify(f"🟢 {reason}: ${round(notional_amount, 2)} {symbol}")


def market_sell_qty(symbol: str, qty: float, entry: float = 0.0, price: float = 0.0, reason="AUTO SELL"):
    rounded_qty = floor_qty(qty, 6)
    if rounded_qty <= 0:
        return

    def submit(q):
        order = MarketOrderRequest(symbol=symbol, qty=q, side=OrderSide.SELL, time_in_force=TimeInForce.DAY)
        trading_client.submit_order(order)

    try:
        submit(rounded_qty)
    except Exception as e:
        err = str(e)
        if is_insufficient_qty_error(err):
            available = parse_available_qty(err)
            retry_qty = floor_qty(available, 6) if available else 0
            if retry_qty > 0 and retry_qty < rounded_qty:
                try:
                    submit(retry_qty)
                    rounded_qty = retry_qty
                except Exception as retry_error:
                    add_alpaca_rejection_event(symbol, reason, f"Initial: {err} | Retry: {retry_error}")
                    raise
            else:
                add_alpaca_rejection_event(symbol, reason, err)
                raise
        else:
            add_alpaca_rejection_event(symbol, reason, err)
            raise

    pnl = (price - entry) * rounded_qty if entry > 0 and price > 0 else 0.0
    pnl_pct = ((price / entry) - 1.0) * 100.0 if entry > 0 and price > 0 else 0.0
    event = {
        "day": today_str(),
        "time": now_time(),
        "side": "SELL",
        "symbol": symbol,
        "qty": rounded_qty,
        "reason": reason,
        "pnl": round(pnl, 4),
        "pnlGbp": round(money_gbp(pnl), 4),
        "pnlPct": round(pnl_pct, 4),
    }
    trade_events.append(event)
    add_trade_history_event(event)
    update_stock_memory_from_sell(symbol, pnl, pnl_pct)
    lock_symbol_until_tomorrow(symbol)
    notify(f"🔴 {reason}: {symbol} | qty={rounded_qty} | est PnL {round(pnl, 4)} ({round(pnl_pct, 2)}%)")


def close_position(position, reason="MANUAL SELL"):
    symbol = position["symbol"]
    qty = position["qty"]
    entry = position["entry"]
    price = position["price"]

    if qty <= DUST_THRESHOLD:
        return {"ok": False, "message": "No open position to sell"}
    if has_open_order(symbol):
        return {"ok": False, "message": f"{symbol} already has open order"}

    market_sell_qty(symbol, qty, entry=entry, price=price, reason=reason)
    if symbol in state:
        state[symbol]["highest_since_entry"] = None
    return {"ok": True, "message": f"{reason} submitted for {symbol}. {symbol} locked until tomorrow.", "symbol": symbol}


def close_position_by_symbol(symbol: str, reason="MANUAL SYMBOL SELL"):
    for p in get_all_positions():
        if p["symbol"] == symbol:
            return close_position(p, reason=reason)
    return {"ok": False, "message": f"No open position found for {symbol}"}


def close_worst_or_largest_position(reason="MANUAL SELL"):
    positions = get_all_positions()
    if not positions:
        return {"ok": False, "message": "No open position to sell"}
    positions.sort(key=lambda p: (p["pnlPct"], -abs(p["marketValue"])))
    return close_position(positions[0], reason=reason)


def close_all_positions(reason="EMERGENCY SELL"):
    results = []
    positions = get_all_positions()
    if not positions:
        return {"ok": False, "message": "No open positions to sell"}
    for p in positions:
        try:
            results.append(close_position(p, reason=reason))
        except Exception as e:
            results.append({"ok": False, "symbol": p["symbol"], "message": str(e)})
    return {"ok": True, "message": f"{reason} attempted for {len(positions)} positions.", "results": results}



# =========================
# FASTER EXIT HELPERS
# =========================
def has_taken_partial_profit(symbol: str):
    return partial_profit_taken.get(symbol.upper()) == today_str()


def mark_partial_profit_taken(symbol: str):
    partial_profit_taken[symbol.upper()] = today_str()


def sell_notional_ok(qty: float, price: float):
    return (float(qty) * float(price)) >= MIN_SELL_NOTIONAL


def partial_profit_qty(position: Dict[str, Any]):
    qty = float(position.get("qty") or 0.0)
    return floor_qty(qty * PARTIAL_PROFIT_SELL_PCT, 6)


def should_partial_profit(position: Dict[str, Any]):
    if not FAST_EXIT_MODE_ENABLED or not PARTIAL_PROFIT_ENABLED:
        return False, "partial profit disabled"

    symbol = position["symbol"]
    if has_taken_partial_profit(symbol):
        return False, "partial profit already taken today"

    pnl_pct = float(position.get("pnlPct") or 0.0)
    price = float(position.get("price") or 0.0)
    qty_to_sell = partial_profit_qty(position)

    if pnl_pct < PARTIAL_PROFIT_TRIGGER_PCT:
        return False, f"pnl {pnl_pct:.2f}% below partial trigger {PARTIAL_PROFIT_TRIGGER_PCT:.2f}%"

    if qty_to_sell <= DUST_THRESHOLD:
        return False, "partial qty too small"

    if not sell_notional_ok(qty_to_sell, price):
        return False, "partial sell notional too small"

    return True, "partial profit trigger"


def should_fast_stop(position: Dict[str, Any]):
    if not FAST_EXIT_MODE_ENABLED:
        return False, "fast exit disabled"

    pnl_pct = float(position.get("pnlPct") or 0.0)
    return pnl_pct <= FAST_STOP_LOSS_PCT, f"fast stop pnl={pnl_pct:.2f}%"


def should_stall_exit(position: Dict[str, Any]):
    if not FAST_EXIT_MODE_ENABLED or not STALL_EXIT_ENABLED:
        return False, "stall exit disabled"

    symbol = position["symbol"]
    minutes = int(position.get("minutesSinceBuy") or 999999)
    pnl_pct = float(position.get("pnlPct") or 0.0)

    if minutes < STALL_EXIT_AFTER_MINUTES:
        return False, f"held {minutes}m below stall timer"

    if pnl_pct > STALL_EXIT_MIN_PNL_PCT:
        return False, f"pnl {pnl_pct:.2f}% above stall minimum"

    if was_bought_today(symbol) and PDT_AWARE_MODE_ENABLED:
        return False, "PDT-aware hold; stall exit skipped today"

    return True, f"stall exit: held {minutes}m pnl={pnl_pct:.2f}%"

# =========================
# STRATEGY
# =========================
def refresh_universe_if_needed(force=False):
    global current_universe, last_universe_refresh_ts

    if AUTO_UNIVERSE_ENABLED:
        try:
            result = build_weekly_universe(force=force)
            if result.get("ok"):
                last_universe_refresh_ts = time.time()
                return
        except Exception as e:
            print(f"AUTO UNIVERSE ERROR: {e}")

    now = time.time()
    if not force and (now - last_universe_refresh_ts) < UNIVERSE_REFRESH_SECONDS:
        return
    current_universe = list(dict.fromkeys(SAFE_UNIVERSE + list(custom_symbols.keys())))
    for s in current_universe:
        ensure_symbol_state(s, custom=s in custom_symbols)
    last_universe_refresh_ts = now
    print(f"UNIVERSE REFRESHED: {', '.join(current_universe)}")


def pick_money_mode_stocks(scans):
    candidates = []
    for scan in scans:
        symbol = scan["symbol"]
        can_buy, reason = can_buy_symbol(symbol)
        if not can_buy:
            continue
        if PDT_AWARE_MODE_ENABLED and today_buy_count() >= MAX_NEW_BUYS_PER_DAY_PDT_AWARE:
            continue
        sniper_ok, sniper_reason = sniper_passes(scan)
        if not sniper_ok:
            print(f"SNIPER SKIP {symbol} | {sniper_reason}")
            continue

        aplus_ok, aplus_reason = a_plus_gate(scan)
        if not aplus_ok:
            print(f"A+ SKIP {symbol} | {aplus_reason}")
            continue
        if not scan["ready_to_buy"]:
            continue
        candidates.append(scan)
    candidates.sort(key=lambda x: (-x["confidence"], -x["quality_score"], x["spread"]))
    return candidates


def get_best_profit_candidate(scans):
    picks = pick_money_mode_stocks(scans)
    return picks[0] if picks else None


def get_weakest_position_for_rotation():
    managed = [p for p in get_all_positions() if p["symbol"] in current_universe]
    if not managed:
        return None
    managed.sort(key=lambda p: (p["pnlPct"], p.get("spread", 0.0)))
    return managed[0]


def maybe_rotate_weakest_into_best(scans):
    global last_rotation_ts
    if not PROFIT_MODE_ENABLED or not ROTATION_MODE_ENABLED or manual_override or emergency_stop:
        return ""
    if time.time() - last_rotation_ts < ROTATION_COOLDOWN_SECONDS:
        return "ROTATION SKIP | cooldown"
    best = get_best_profit_candidate(scans)
    weakest = get_weakest_position_for_rotation()
    if not best or not weakest or best["symbol"] == weakest["symbol"]:
        return "ROTATION SKIP | no useful rotation"
    if weakest["pnlPct"] > ROTATE_ONLY_IF_WEAKEST_PNL_BELOW:
        return f"ROTATION SKIP | weakest {weakest['symbol']} still okay"
    if pdt_aware_should_avoid_sell(weakest["symbol"], f"PROFIT MODE ROTATE OUT FOR {best['symbol']}", weakest["pnlPct"]):
        return f"ROTATION SKIP | PDT-aware hold for {weakest['symbol']}"
    try:
        sell_result = close_position(weakest, reason=f"PROFIT MODE ROTATE OUT FOR {best['symbol']}")
        if not sell_result.get("ok"):
            return f"ROTATION SELL BLOCKED | {sell_result.get('message')}"
        time.sleep(2)
        notional = confidence_notional(best)
        if notional < MIN_ORDER_NOTIONAL:
            return "ROTATION BUY SKIP | no buying power"
        market_buy_notional(best["symbol"], notional, reason=f"PROFIT MODE ROTATE INTO FROM {weakest['symbol']}")
        last_rotation_ts = time.time()
        return f"ROTATION DONE | sold {weakest['symbol']} -> bought {best['symbol']} ${notional:.2f}"
    except Exception as e:
        return f"ROTATION ERROR | {e}"


def manage_money_mode_positions():
    for p in get_all_positions():
        symbol = p["symbol"]

        if not MANAGE_OUTSIDE_UNIVERSE_POSITIONS and symbol not in current_universe:
            continue

        if has_open_order(symbol):
            continue

        price = float(p["price"])
        entry = float(p["entry"])
        qty = float(p["qty"])
        highest = p["highest"]

        if price <= 0 or entry <= 0 or qty <= DUST_THRESHOLD:
            continue

        fast_stop, fast_stop_reason = should_fast_stop(p)
        if fast_stop:
            try:
                if pdt_aware_should_avoid_sell(symbol, "FAST EXIT STOP LOSS", p["pnlPct"], allow_hard_stop=True):
                    continue

                market_sell_qty(symbol, qty, entry=entry, price=price, reason="FAST EXIT STOP LOSS")
                state[symbol]["highest_since_entry"] = None
                print(f"FAST EXIT STOP LOSS SELL {qty:.6f} {symbol}")
            except Exception as e:
                print(f"SELL ERROR {symbol}: {e}")
            continue

        stop_price = entry * STOP_LOSS
        if price <= stop_price:
            try:
                if pdt_aware_should_avoid_sell(symbol, "MONEY MODE STOP LOSS", p["pnlPct"], allow_hard_stop=True):
                    continue

                market_sell_qty(symbol, qty, entry=entry, price=price, reason="MONEY MODE STOP LOSS")
                state[symbol]["highest_since_entry"] = None
            except Exception as e:
                print(f"SELL ERROR {symbol}: {e}")
            continue

        partial_ok, partial_reason = should_partial_profit(p)
        if partial_ok:
            try:
                if pdt_aware_should_avoid_sell(symbol, "PARTIAL PROFIT TAKE", p["pnlPct"], allow_hard_stop=False):
                    continue

                sell_qty = partial_profit_qty(p)
                market_sell_qty(symbol, sell_qty, entry=entry, price=price, reason="PARTIAL PROFIT TAKE")
                mark_partial_profit_taken(symbol)
                print(f"PARTIAL PROFIT SELL {sell_qty:.6f} {symbol}")
            except Exception as e:
                print(f"PARTIAL SELL ERROR {symbol}: {e}")
            continue

        stall_ok, stall_reason = should_stall_exit(p)
        if stall_ok:
            try:
                if pdt_aware_should_avoid_sell(symbol, "STALL EXIT", p["pnlPct"], allow_hard_stop=False):
                    continue

                market_sell_qty(symbol, qty, entry=entry, price=price, reason="STALL EXIT")
                state[symbol]["highest_since_entry"] = None
                print(f"STALL EXIT SELL {qty:.6f} {symbol} | {stall_reason}")
            except Exception as e:
                print(f"STALL SELL ERROR {symbol}: {e}")
            continue

        trail_start_price = entry * TRAIL_START
        if price >= trail_start_price and highest is not None:
            giveback = POST_PARTIAL_TRAIL_GIVEBACK if has_taken_partial_profit(symbol) else TRAIL_GIVEBACK
            trail_floor = highest * giveback

            if price <= trail_floor:
                try:
                    if pdt_aware_should_avoid_sell(symbol, "MONEY MODE TRAILING PROFIT", p["pnlPct"]):
                        continue

                    market_sell_qty(symbol, qty, entry=entry, price=price, reason="MONEY MODE TRAILING PROFIT")
                    state[symbol]["highest_since_entry"] = None
                except Exception as e:
                    print(f"SELL ERROR {symbol}: {e}")
                continue

def money_mode_buy(scans, manual=False):
    if emergency_stop:
        return "BUY BLOCKED | emergency stop active"
    blocked, reason = risk_blocked()
    if blocked:
        return f"BUY BLOCKED | {reason}"
    if allowed_new_position_count() <= 0:
        return f"BUY BLOCKED | max positions reached ({MAX_POSITIONS})"
    if PDT_AWARE_MODE_ENABLED and today_buy_count() >= MAX_NEW_BUYS_PER_DAY_PDT_AWARE:
        return f"BUY BLOCKED | PDT-aware max new buys today reached ({MAX_NEW_BUYS_PER_DAY_PDT_AWARE})"

    picks = pick_money_mode_stocks(scans)
    if manual and not picks:
        if A_PLUS_BLOCK_LOW_CONFIDENCE_MANUAL_BUY:
            return "No A+ sniper candidates ready. Manual Money Buy blocked by Trade Quality Gate."
        picks = [s for s in scans if can_buy_symbol(s["symbol"])[0] and s["spread"] <= MAX_SPREAD]
        picks.sort(key=lambda x: (-x["confidence"], -x["quality_score"], x["spread"]))

    if not picks:
        return "No sniper candidates ready."

    bought = 0
    messages = []
    for c in picks:
        if bought >= MAX_NEW_BUYS_PER_LOOP:
            break
        symbol = c["symbol"]
        can_buy, reason = can_buy_symbol(symbol)
        if not can_buy:
            messages.append(f"SKIP {symbol} | {reason}")
            continue
        notional = confidence_notional(c)
        if notional < MIN_ORDER_NOTIONAL:
            messages.append(f"SKIP {symbol} | notional too small {notional:.2f}")
            continue
        confidence, label = calculate_confidence(c)
        reason = f"{'MANUAL' if manual else 'AUTO'} SNIPER {label} BUY"
        try:
            market_buy_notional(symbol, notional, reason=reason)
            state[symbol]["ref"] = c["price"]
            state[symbol]["highest_since_entry"] = c["price"]
            messages.append(f"{reason} ${notional:.2f} {symbol} confidence={confidence:.2f}")
            bought += 1
        except Exception as e:
            messages.append(f"BUY ERROR {symbol}: {e}")
    return " | ".join(messages)


def buy_custom_symbol(symbol: str):
    symbol = symbol.upper().strip()
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        return {"ok": False, "message": "Invalid ticker"}
    if CUSTOM_BUY_REQUIRES_MARKET_OPEN and not trading_client.get_clock().is_open:
        return {"ok": False, "message": "Market closed"}
    can_buy, reason = can_buy_symbol(symbol)
    if not can_buy:
        return {"ok": False, "message": f"BUY BLOCKED | {reason}"}
    quote = get_quote(symbol)
    if quote["spread"] > MAX_SPREAD:
        return {"ok": False, "message": f"BUY BLOCKED | {symbol} spread too wide: {quote['spread']:.4f}"}
    add_symbol_to_universe(symbol, custom=True)
    fake_scan = {"symbol": symbol, "quality_score": 0.03, "spread": quote["spread"], "short_momentum": 0, "pullback": 0.01}
    notional = confidence_notional(fake_scan)
    market_buy_notional(symbol, notional, reason="CUSTOM SNIPER BUY")
    return {"ok": True, "message": f"CUSTOM BUY ${notional:.2f} of {symbol}. Added to managed universe."}



# =========================
# SQLITE PERSISTENT STORAGE
# =========================
def db_connect():
    conn = sqlite3.connect(SQLITE_DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    if not SQLITE_ENABLED:
        return

    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alpaca_order_id TEXT UNIQUE,
            timestamp TEXT NOT NULL,
            day TEXT,
            time TEXT,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL,
            price REAL,
            amount REAL,
            amount_gbp REAL,
            pnl REAL,
            pnl_gbp REAL,
            pnl_pct REAL,
            reason TEXT,
            equity REAL,
            equity_gbp REAL,
            fx_rate REAL,
            source TEXT DEFAULT 'bot'
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_timestamp
        ON trades(timestamp)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_symbol
        ON trades(symbol)
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS closed_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_sell_order_id TEXT,
            source_buy_order_id TEXT,
            timestamp TEXT NOT NULL,
            day TEXT,
            time TEXT,
            symbol TEXT NOT NULL,
            qty REAL,
            entry_price REAL,
            exit_price REAL,
            pnl REAL,
            pnl_gbp REAL,
            pnl_pct REAL,
            fx_rate REAL,
            reason TEXT,
            source TEXT DEFAULT 'matcher'
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_closed_trades_timestamp
        ON closed_trades(timestamp)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_closed_trades_symbol
        ON closed_trades(symbol)
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS weekly_universe (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            symbol TEXT NOT NULL,
            score REAL,
            reason TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(week_start, symbol)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS universe_refresh_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            refreshed_at TEXT NOT NULL,
            week_start TEXT NOT NULL,
            symbols TEXT,
            reason TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_trade_to_db(event: Dict[str, Any], source: str = "bot"):
    if not SQLITE_ENABLED:
        return

    try:
        init_db()
        conn = db_connect()
        cur = conn.cursor()

        timestamp = event.get("timestamp") or datetime.now(UTC).isoformat()
        equity = float(event.get("equity") or 0.0)
        equity_gbp = float(event.get("equityGbp") or money_gbp(equity))
        fx_rate = float(event.get("fxRate") or get_usd_to_gbp_rate())

        cur.execute("""
            INSERT OR IGNORE INTO trades (
                alpaca_order_id, timestamp, day, time, symbol, side, qty, price,
                amount, amount_gbp, pnl, pnl_gbp, pnl_pct, reason,
                equity, equity_gbp, fx_rate, source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.get("alpacaOrderId"),
            timestamp,
            event.get("day"),
            event.get("time"),
            event.get("symbol"),
            event.get("side"),
            float(event.get("qty") or 0.0),
            float(event.get("price") or 0.0),
            float(event.get("amount") or 0.0),
            float(event.get("amountGbp") or money_gbp(float(event.get("amount") or 0.0))),
            float(event.get("pnl") or 0.0),
            float(event.get("pnlGbp") or money_gbp(float(event.get("pnl") or 0.0))),
            float(event.get("pnlPct") or 0.0),
            event.get("reason", ""),
            equity,
            equity_gbp,
            fx_rate,
            source,
        ))

        conn.commit()
        conn.close()

    except Exception as e:
        print(f"DB SAVE ERROR: {e}")


def trades_from_db(limit: int = 1000):
    if not SQLITE_ENABLED:
        return trade_history[-limit:]

    try:
        init_db()
        conn = db_connect()
        rows = conn.execute("""
            SELECT * FROM trades
            ORDER BY timestamp ASC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()

        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "alpacaOrderId": r["alpaca_order_id"],
                "timestamp": r["timestamp"],
                "day": r["day"],
                "time": r["time"],
                "symbol": r["symbol"],
                "side": r["side"],
                "qty": r["qty"],
                "price": r["price"],
                "amount": r["amount"],
                "amountGbp": r["amount_gbp"],
                "pnl": r["pnl"],
                "pnlGbp": r["pnl_gbp"],
                "pnlPct": r["pnl_pct"],
                "reason": r["reason"],
                "equity": r["equity"],
                "equityGbp": r["equity_gbp"],
                "fxRate": r["fx_rate"],
                "source": r["source"],
            })
        return items
    except Exception as e:
        print(f"DB READ ERROR: {e}")
        return trade_history[-limit:]


def stock_memory_from_db():
    trades = trades_from_db(5000)
    memory: Dict[str, Dict[str, Any]] = {}

    for t in trades:
        if t.get("side") != "SELL":
            continue

        symbol = str(t.get("symbol", "")).upper()
        if not symbol:
            continue

        if symbol not in memory:
            memory[symbol] = {
                "wins": 0,
                "losses": 0,
                "trades": 0,
                "totalPnl": 0.0,
                "totalPnlGbp": 0.0,
                "totalPnlPct": 0.0,
                "avgPnl": 0.0,
                "avgPnlGbp": 0.0,
                "avgPnlPct": 0.0,
                "winRate": 0.0,
                "trust": "NEW",
                "lastResult": "—",
            }

        m = memory[symbol]
        pnl = float(t.get("pnl") or 0.0)
        pnl_gbp = float(t.get("pnlGbp") or 0.0)
        pnl_pct = float(t.get("pnlPct") or 0.0)

        m["trades"] += 1
        m["totalPnl"] += pnl
        m["totalPnlGbp"] += pnl_gbp
        m["totalPnlPct"] += pnl_pct

        if pnl >= 0:
            m["wins"] += 1
            m["lastResult"] = "WIN"
        else:
            m["losses"] += 1
            m["lastResult"] = "LOSS"

    for symbol, m in memory.items():
        m["winRate"] = m["wins"] / max(1, m["trades"])
        m["avgPnl"] = m["totalPnl"] / max(1, m["trades"])
        m["avgPnlGbp"] = m["totalPnlGbp"] / max(1, m["trades"])
        m["avgPnlPct"] = m["totalPnlPct"] / max(1, m["trades"])

        if m["trades"] < MEMORY_MIN_TRADES_FOR_TRUST:
            m["trust"] = "NEW"
        elif m["winRate"] >= MEMORY_GOOD_WINRATE:
            m["trust"] = "GOOD"
        elif m["winRate"] <= MEMORY_BAD_WINRATE:
            m["trust"] = "BAD"
        else:
            m["trust"] = "NEUTRAL"

    items = [{"symbol": s, **m} for s, m in memory.items()]
    items.sort(key=lambda x: (-x.get("totalPnl", 0), -x.get("winRate", 0), -x.get("trades", 0)))
    return items


def db_summary_payload():
    trades = trades_from_db(5000)
    sells = [t for t in trades if t.get("side") == "SELL"]
    wins = [t for t in sells if float(t.get("pnl") or 0.0) >= 0]
    total_pnl = sum(float(t.get("pnl") or 0.0) for t in sells)
    total_pnl_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in sells)

    return {
        "enabled": SQLITE_ENABLED,
        "dbFile": SQLITE_DB_FILE,
        "totalTrades": len(trades),
        "sellTrades": len(sells),
        "wins": len(wins),
        "losses": max(0, len(sells) - len(wins)),
        "winRate": len(wins) / max(1, len(sells)),
        "totalPnl": total_pnl,
        "totalPnlGbp": total_pnl_gbp,
    }


def parse_order_timestamp(order):
    for attr in ["filled_at", "updated_at", "submitted_at", "created_at"]:
        try:
            value = getattr(order, attr, None)
            if value:
                return value
        except Exception:
            pass
    return datetime.now(UTC)



def clear_closed_trades():
    if not SQLITE_ENABLED:
        return
    init_db()
    conn = db_connect()
    conn.execute("DELETE FROM closed_trades")
    conn.commit()
    conn.close()


def save_closed_trade_to_db(trade: Dict[str, Any]):
    if not SQLITE_ENABLED:
        return

    init_db()
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO closed_trades (
            source_sell_order_id, source_buy_order_id, timestamp, day, time,
            symbol, qty, entry_price, exit_price, pnl, pnl_gbp, pnl_pct,
            fx_rate, reason, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        trade.get("sourceSellOrderId"),
        trade.get("sourceBuyOrderId"),
        trade.get("timestamp"),
        trade.get("day"),
        trade.get("time"),
        trade.get("symbol"),
        float(trade.get("qty") or 0.0),
        float(trade.get("entryPrice") or 0.0),
        float(trade.get("exitPrice") or 0.0),
        float(trade.get("pnl") or 0.0),
        float(trade.get("pnlGbp") or 0.0),
        float(trade.get("pnlPct") or 0.0),
        float(trade.get("fxRate") or get_usd_to_gbp_rate()),
        trade.get("reason", ""),
        trade.get("source", "matcher"),
    ))

    conn.commit()
    conn.close()


def closed_trades_from_db(limit: int = 1000):
    if not SQLITE_ENABLED:
        return []

    try:
        init_db()
        conn = db_connect()
        rows = conn.execute("""
            SELECT * FROM closed_trades
            ORDER BY timestamp ASC
            LIMIT ?
        """, (limit,)).fetchall()
        conn.close()

        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "day": r["day"],
                "time": r["time"],
                "symbol": r["symbol"],
                "side": "SELL",
                "qty": r["qty"],
                "entryPrice": r["entry_price"],
                "exitPrice": r["exit_price"],
                "price": r["exit_price"],
                "pnl": r["pnl"],
                "pnlGbp": r["pnl_gbp"],
                "pnlPct": r["pnl_pct"],
                "fxRate": r["fx_rate"],
                "reason": r["reason"],
                "source": r["source"],
                "equity": 0.0,
                "equityGbp": 0.0,
            }
            for r in rows
        ]

    except Exception as e:
        print(f"CLOSED TRADES READ ERROR: {e}")
        return []


def rebuild_closed_trades_from_orders():
    """
    Reads raw BUY/SELL rows from trades table and rebuilds completed trades
    using FIFO matching. This is the important fix for realised PnL.
    """
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}

    init_db()
    clear_closed_trades()

    conn = db_connect()
    rows = conn.execute("""
        SELECT *
        FROM trades
        WHERE symbol IS NOT NULL
          AND side IN ('BUY', 'SELL')
          AND qty > 0
        ORDER BY timestamp ASC, id ASC
    """).fetchall()
    conn.close()

    open_lots: Dict[str, List[Dict[str, Any]]] = {}
    closed_count = 0
    unmatched_sells = 0
    rate = get_usd_to_gbp_rate()

    for r in rows:
        symbol = str(r["symbol"]).upper()
        side = str(r["side"]).upper()
        qty = float(r["qty"] or 0.0)
        price = float(r["price"] or 0.0)

        # Backfilled BUY rows may have amount but no price in older DB rows.
        if price <= 0 and qty > 0:
            amount = float(r["amount"] or 0.0)
            if amount > 0:
                price = amount / qty

        if qty <= 0 or price <= 0:
            continue

        if side == "BUY":
            open_lots.setdefault(symbol, []).append({
                "qty": qty,
                "price": price,
                "order_id": r["alpaca_order_id"],
                "timestamp": r["timestamp"],
            })
            continue

        if side == "SELL":
            remaining = qty
            lots = open_lots.setdefault(symbol, [])

            while remaining > 1e-9 and lots:
                lot = lots[0]
                used_qty = min(remaining, float(lot["qty"]))
                entry_price = float(lot["price"])
                exit_price = price

                pnl = (exit_price - entry_price) * used_qty
                pnl_pct = ((exit_price / entry_price) - 1.0) * 100.0 if entry_price > 0 else 0.0

                trade = {
                    "sourceSellOrderId": r["alpaca_order_id"],
                    "sourceBuyOrderId": lot.get("order_id"),
                    "timestamp": r["timestamp"],
                    "day": r["day"],
                    "time": r["time"],
                    "symbol": symbol,
                    "qty": used_qty,
                    "entryPrice": entry_price,
                    "exitPrice": exit_price,
                    "pnl": round(pnl, 6),
                    "pnlGbp": round(pnl * rate, 6),
                    "pnlPct": round(pnl_pct, 6),
                    "fxRate": rate,
                    "reason": "FIFO MATCHED CLOSED TRADE",
                    "source": "fifo_matcher",
                }

                save_closed_trade_to_db(trade)
                closed_count += 1

                lot["qty"] = float(lot["qty"]) - used_qty
                remaining -= used_qty

                if lot["qty"] <= 1e-9:
                    lots.pop(0)

            if remaining > 1e-9:
                unmatched_sells += 1

    return {
        "ok": True,
        "message": f"Closed-trade rebuild complete. Matched {closed_count} closed trades. Unmatched sells: {unmatched_sells}.",
        "matchedClosedTrades": closed_count,
        "unmatchedSells": unmatched_sells,
    }


def closed_trade_summary_payload():
    closed = closed_trades_from_db(10000)
    wins = [t for t in closed if float(t.get("pnl") or 0.0) >= 0]
    losses = [t for t in closed if float(t.get("pnl") or 0.0) < 0]
    total_pnl = sum(float(t.get("pnl") or 0.0) for t in closed)
    total_pnl_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in closed)

    return {
        "closedTrades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": len(wins) / max(1, len(closed)),
        "totalPnl": total_pnl,
        "totalPnlGbp": total_pnl_gbp,
    }


def stock_memory_from_closed_trades():
    closed = closed_trades_from_db(10000)
    memory: Dict[str, Dict[str, Any]] = {}

    for t in closed:
        symbol = str(t.get("symbol", "")).upper()
        if not symbol:
            continue

        if symbol not in memory:
            memory[symbol] = {
                "wins": 0,
                "losses": 0,
                "trades": 0,
                "totalPnl": 0.0,
                "totalPnlGbp": 0.0,
                "totalPnlPct": 0.0,
                "avgPnl": 0.0,
                "avgPnlGbp": 0.0,
                "avgPnlPct": 0.0,
                "winRate": 0.0,
                "trust": "NEW",
                "lastResult": "—",
            }

        m = memory[symbol]
        pnl = float(t.get("pnl") or 0.0)
        pnl_gbp = float(t.get("pnlGbp") or 0.0)
        pnl_pct = float(t.get("pnlPct") or 0.0)

        m["trades"] += 1
        m["totalPnl"] += pnl
        m["totalPnlGbp"] += pnl_gbp
        m["totalPnlPct"] += pnl_pct

        if pnl >= 0:
            m["wins"] += 1
            m["lastResult"] = "WIN"
        else:
            m["losses"] += 1
            m["lastResult"] = "LOSS"

    for symbol, m in memory.items():
        m["winRate"] = m["wins"] / max(1, m["trades"])
        m["avgPnl"] = m["totalPnl"] / max(1, m["trades"])
        m["avgPnlGbp"] = m["totalPnlGbp"] / max(1, m["trades"])
        m["avgPnlPct"] = m["totalPnlPct"] / max(1, m["trades"])

        if m["trades"] < MEMORY_MIN_TRADES_FOR_TRUST:
            m["trust"] = "NEW"
        elif m["winRate"] >= MEMORY_GOOD_WINRATE:
            m["trust"] = "GOOD"
        elif m["winRate"] <= MEMORY_BAD_WINRATE:
            m["trust"] = "BAD"
        else:
            m["trust"] = "NEUTRAL"

    items = [{"symbol": s, **m} for s, m in memory.items()]
    items.sort(key=lambda x: (-x.get("totalPnl", 0), -x.get("winRate", 0), -x.get("trades", 0)))
    return items


def order_is_filled(order):
    try:
        filled_qty = float(getattr(order, "filled_qty", 0) or 0)
        return filled_qty > 0
    except Exception:
        return False


def get_order_side(order):
    return str(getattr(order, "side", "")).upper()


def get_order_symbol(order):
    return str(getattr(order, "symbol", "")).upper()


def get_order_price(order):
    try:
        price = float(getattr(order, "filled_avg_price", 0) or 0)
        if price > 0:
            return price
    except Exception:
        pass
    try:
        limit_price = float(getattr(order, "limit_price", 0) or 0)
        if limit_price > 0:
            return limit_price
    except Exception:
        pass
    return 0.0


def get_order_qty(order):
    try:
        return float(getattr(order, "filled_qty", 0) or 0)
    except Exception:
        return 0.0


def get_order_id(order):
    try:
        return str(getattr(order, "id", ""))
    except Exception:
        return ""



def get_query_order_status_all():
    try:
        return QueryOrderStatus.ALL
    except Exception:
        # Some alpaca-py versions represent all as lowercase string.
        return "all"


def fetch_all_orders_paginated():
    """
    Alpaca-py pagination/backfill.
    Pulls ALL orders backwards in chunks using `until`, same idea as the user-provided snippet.
    """
    all_orders = []
    until = datetime.now(UTC)
    seen_ids = set()

    for page in range(BACKFILL_MAX_PAGES):
        try:
            req = GetOrdersRequest(
                status=get_query_order_status_all(),
                limit=BACKFILL_CHUNK_SIZE,
                until=until,
                direction="desc",
                nested=False,
            )
        except TypeError:
            # Some alpaca-py versions may not accept nested.
            req = GetOrdersRequest(
                status=get_query_order_status_all(),
                limit=BACKFILL_CHUNK_SIZE,
                until=until,
                direction="desc",
            )

        chunk = trading_client.get_orders(filter=req)

        if not chunk:
            break

        new_count = 0
        earliest = None

        for order in chunk:
            oid = get_order_id(order)
            if oid and oid in seen_ids:
                continue

            if oid:
                seen_ids.add(oid)

            all_orders.append(order)
            new_count += 1

            ts = parse_order_timestamp(order)
            if earliest is None or str(ts) < str(earliest):
                earliest = ts

        print(f"BACKFILL PAGE {page + 1}: fetched={len(chunk)} new={new_count}")

        if new_count == 0 or len(chunk) < BACKFILL_CHUNK_SIZE:
            break

        # Move until backwards to the earliest order timestamp in this chunk.
        if earliest:
            try:
                until = earliest - timedelta(microseconds=1)
            except Exception:
                # If alpaca returns string timestamps.
                try:
                    until = datetime.fromisoformat(str(earliest).replace("Z", "+00:00")) - timedelta(microseconds=1)
                except Exception:
                    break
        else:
            break

    return all_orders


def backfill_trades_from_alpaca_full():
    init_db()

    orders = fetch_all_orders_paginated()
    imported = 0
    skipped = 0
    rate = get_usd_to_gbp_rate()

    # Sort oldest -> newest before saving/matching.
    sorted_orders = sorted(orders, key=lambda o: str(parse_order_timestamp(o)))

    for order in sorted_orders:
        try:
            if not order_is_filled(order):
                skipped += 1
                continue

            symbol = get_order_symbol(order)
            side = get_order_side(order)
            qty = get_order_qty(order)
            price = get_order_price(order)
            oid = get_order_id(order)

            if not symbol or side not in ["BUY", "SELL"] or qty <= 0:
                skipped += 1
                continue

            # If price is missing, skip for PnL safety.
            if price <= 0:
                skipped += 1
                continue

            timestamp_obj = parse_order_timestamp(order)

            if hasattr(timestamp_obj, "isoformat"):
                timestamp = timestamp_obj.isoformat()
                try:
                    day = timestamp_obj.astimezone(UTC).strftime("%Y-%m-%d")
                    tm = timestamp_obj.astimezone(UTC).strftime("%H:%M:%S")
                except Exception:
                    day = today_str()
                    tm = now_time()
            else:
                timestamp = str(timestamp_obj)
                day = today_str()
                tm = now_time()

            amount = qty * price

            event = {
                "alpacaOrderId": oid,
                "timestamp": timestamp,
                "day": day,
                "time": tm,
                "side": side,
                "symbol": symbol,
                "qty": qty,
                "price": price,
                "amount": amount if side == "BUY" else 0.0,
                "amountGbp": amount * rate if side == "BUY" else 0.0,
                "pnl": 0.0,
                "pnlGbp": 0.0,
                "pnlPct": 0.0,
                "reason": "ALPACA FULL BACKFILL",
                "equity": 0.0,
                "equityGbp": 0.0,
                "fxRate": rate,
            }

            before = db_summary_payload().get("totalTrades", 0)
            save_trade_to_db(event, source="alpaca_full_backfill")
            after = db_summary_payload().get("totalTrades", 0)

            if after > before:
                imported += 1
            else:
                skipped += 1

        except Exception as e:
            print(f"FULL BACKFILL ORDER ERROR: {e}")
            skipped += 1

    match_result = rebuild_closed_trades_from_orders()

    return {
        "ok": True,
        "message": f"Full ALL-orders backfill complete. Orders fetched {len(orders)}. Imported {imported}, skipped {skipped}. {match_result.get('message', '')}",
        "ordersFetched": len(orders),
        "imported": imported,
        "skipped": skipped,
        **match_result,
    }


def backfill_trades_from_alpaca():
    init_db()

    request = GetOrdersRequest(
        status=get_query_order_status_all(),
        limit=BACKFILL_ORDER_LIMIT,
    )

    orders = trading_client.get_orders(filter=request)
    imported = 0
    skipped = 0
    rate = get_usd_to_gbp_rate()

    # Keep a simple FIFO-ish entry tracker for pnl approximation.
    open_entries: Dict[str, List[Dict[str, float]]] = {}

    sorted_orders = sorted(orders, key=lambda o: str(parse_order_timestamp(o)))

    for order in sorted_orders:
        try:
            status = str(getattr(order, "status", "")).lower()
            filled_qty = float(getattr(order, "filled_qty", 0) or 0)

            if filled_qty <= 0:
                skipped += 1
                continue

            symbol = str(getattr(order, "symbol", "")).upper()
            side = str(getattr(order, "side", "")).upper()
            filled_avg_price = float(getattr(order, "filled_avg_price", 0) or 0)
            timestamp_obj = parse_order_timestamp(order)

            if hasattr(timestamp_obj, "isoformat"):
                timestamp = timestamp_obj.isoformat()
                day = timestamp_obj.astimezone(UTC).strftime("%Y-%m-%d") if hasattr(timestamp_obj, "astimezone") else today_str()
                tm = timestamp_obj.astimezone(UTC).strftime("%H:%M:%S") if hasattr(timestamp_obj, "astimezone") else now_time()
            else:
                timestamp = str(timestamp_obj)
                day = today_str()
                tm = now_time()

            amount = filled_qty * filled_avg_price
            pnl = 0.0
            pnl_pct = 0.0

            if side == "BUY":
                open_entries.setdefault(symbol, []).append({
                    "qty": filled_qty,
                    "price": filled_avg_price,
                })

            if side == "SELL":
                remaining = filled_qty
                cost = 0.0
                matched_qty = 0.0
                entries = open_entries.setdefault(symbol, [])

                while remaining > 0 and entries:
                    entry = entries[0]
                    use_qty = min(remaining, entry["qty"])
                    cost += use_qty * entry["price"]
                    matched_qty += use_qty
                    entry["qty"] -= use_qty
                    remaining -= use_qty

                    if entry["qty"] <= 1e-9:
                        entries.pop(0)

                if matched_qty > 0 and cost > 0:
                    proceeds = matched_qty * filled_avg_price
                    pnl = proceeds - cost
                    avg_entry = cost / matched_qty
                    pnl_pct = ((filled_avg_price / avg_entry) - 1.0) * 100.0

            event = {
                "alpacaOrderId": str(getattr(order, "id", "")),
                "timestamp": timestamp,
                "day": day,
                "time": tm,
                "side": side,
                "symbol": symbol,
                "qty": filled_qty,
                "price": filled_avg_price,
                "amount": amount if side == "BUY" else 0.0,
                "amountGbp": amount * rate if side == "BUY" else 0.0,
                "pnl": round(pnl, 4),
                "pnlGbp": round(pnl * rate, 4),
                "pnlPct": round(pnl_pct, 4),
                "reason": "ALPACA BACKFILL",
                "equity": 0.0,
                "equityGbp": 0.0,
                "fxRate": rate,
            }

            before = len(trades_from_db(10000))
            save_trade_to_db(event, source="alpaca_backfill")
            after = len(trades_from_db(10000))

            if after > before:
                imported += 1
            else:
                skipped += 1

        except Exception as e:
            print(f"BACKFILL ORDER ERROR: {e}")
            skipped += 1

    match_result = rebuild_closed_trades_from_orders()

    return {
        "ok": True,
        "message": f"Backfill complete. Imported {imported}, skipped {skipped}. {match_result.get('message', '')}",
        "imported": imported,
        "skipped": skipped,
        **match_result,
    }



# =========================
# PROFIT OPTIMISER / ANALYTICS / AUTO IMPROVE
# =========================
def today_realised_pnl():
    today = today_str()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    return sum(float(t.get("pnl") or 0.0) for t in closed if t.get("day") == today)


def today_realised_pnl_gbp():
    today = today_str()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    return sum(float(t.get("pnlGbp") or 0.0) for t in closed if t.get("day") == today)


def profit_guardrail_status():
    pnl = today_realised_pnl()
    if PAUSE_BUYS_AFTER_DAILY_TARGET and pnl >= DAILY_PROFIT_TARGET:
        return True, f"Daily profit target hit: ${pnl:.2f}"
    if PAUSE_BUYS_AFTER_DAILY_LOSS and pnl <= DAILY_LOSS_LIMIT_OPTIMIZER:
        return True, f"Daily optimiser loss limit hit: ${pnl:.2f}"
    return False, ""


def analytics_payload():
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    wins = [t for t in closed if float(t.get("pnl") or 0.0) >= 0]
    losses = [t for t in closed if float(t.get("pnl") or 0.0) < 0]
    total_pnl = sum(float(t.get("pnl") or 0.0) for t in closed)
    total_pnl_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in closed)
    gross_win = sum(float(t.get("pnl") or 0.0) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl") or 0.0) for t in losses))
    avg_win = gross_win / max(1, len(wins))
    avg_loss = -gross_loss / max(1, len(losses))
    avg_win_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in wins) / max(1, len(wins))
    avg_loss_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in losses) / max(1, len(losses))

    by_symbol = {}
    for t in closed:
        symbol = str(t.get("symbol", "")).upper()
        if not symbol:
            continue
        row = by_symbol.setdefault(symbol, {"symbol": symbol, "trades": 0, "wins": 0, "losses": 0, "totalPnl": 0.0, "totalPnlGbp": 0.0, "winRate": 0.0, "avgPnl": 0.0, "trust": "NEW"})
        pnl = float(t.get("pnl") or 0.0)
        row["trades"] += 1
        row["totalPnl"] += pnl
        row["totalPnlGbp"] += float(t.get("pnlGbp") or 0.0)
        if pnl >= 0:
            row["wins"] += 1
        else:
            row["losses"] += 1

    rows = []
    for row in by_symbol.values():
        row["winRate"] = row["wins"] / max(1, row["trades"])
        row["avgPnl"] = row["totalPnl"] / max(1, row["trades"])
        if row["trades"] >= AUTO_BOOST_MIN_TRADES and row["winRate"] >= AUTO_BOOST_MIN_WINRATE and row["totalPnl"] >= AUTO_BOOST_MIN_TOTAL_PNL:
            row["trust"] = "BOOST"
        elif row["trades"] >= AUTO_BLACKLIST_MIN_TRADES and row["winRate"] <= AUTO_BLACKLIST_MAX_WINRATE and row["totalPnl"] <= AUTO_BLACKLIST_MAX_TOTAL_PNL:
            row["trust"] = "BLACKLIST"
        elif row["trades"] >= 3:
            row["trust"] = "NEUTRAL"
        rows.append(row)

    return {
        "enabled": ANALYTICS_ENABLED,
        "closedTrades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": len(wins) / max(1, len(closed)),
        "totalPnl": total_pnl,
        "totalPnlGbp": total_pnl_gbp,
        "averageWin": avg_win,
        "averageLoss": avg_loss,
        "averageWinGbp": avg_win_gbp,
        "averageLossGbp": avg_loss_gbp,
        "profitFactor": gross_win / max(0.01, gross_loss),
        "bestStocks": sorted(rows, key=lambda x: (x["totalPnl"], x["winRate"]), reverse=True)[:10],
        "worstStocks": sorted(rows, key=lambda x: (x["totalPnl"], x["winRate"]))[:10],
        "todayRealisedPnl": today_realised_pnl(),
        "todayRealisedPnlGbp": today_realised_pnl_gbp(),
    }


def symbol_stats(symbol: str):
    symbol = symbol.upper()
    rows = analytics_payload().get("bestStocks", []) + analytics_payload().get("worstStocks", [])
    for row in rows:
        if row.get("symbol") == symbol:
            return row
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    trades = [t for t in closed if str(t.get("symbol", "")).upper() == symbol]
    wins = [t for t in trades if float(t.get("pnl") or 0.0) >= 0]
    total = sum(float(t.get("pnl") or 0.0) for t in trades)
    return {"symbol": symbol, "trades": len(trades), "wins": len(wins), "winRate": len(wins) / max(1, len(trades)), "totalPnl": total}


def auto_improve_decision(symbol: str):
    if not AUTO_IMPROVE_ENABLED:
        return {"action": "NORMAL", "multiplier": 1.0, "reason": "auto improve off"}
    row = symbol_stats(symbol)
    trades = int(row.get("trades") or 0)
    win_rate = float(row.get("winRate") or 0.0)
    total_pnl = float(row.get("totalPnl") or 0.0)
    if AUTO_BLACKLIST_ENABLED and trades >= AUTO_BLACKLIST_MIN_TRADES and win_rate <= AUTO_BLACKLIST_MAX_WINRATE and total_pnl <= AUTO_BLACKLIST_MAX_TOTAL_PNL:
        return {"action": "BLACKLIST", "multiplier": 0.0, "reason": f"weak history: trades={trades}, winRate={win_rate:.2f}, pnl=${total_pnl:.2f}"}
    if AUTO_BOOST_ENABLED and trades >= AUTO_BOOST_MIN_TRADES and win_rate >= AUTO_BOOST_MIN_WINRATE and total_pnl >= AUTO_BOOST_MIN_TOTAL_PNL:
        return {"action": "BOOST", "multiplier": AUTO_BOOST_MULTIPLIER, "reason": f"strong history: trades={trades}, winRate={win_rate:.2f}, pnl=${total_pnl:.2f}"}
    if trades >= AUTO_BLACKLIST_MIN_TRADES and total_pnl < 0:
        return {"action": "REDUCE", "multiplier": AUTO_REDUCE_MULTIPLIER, "reason": f"negative history: trades={trades}, pnl=${total_pnl:.2f}"}
    return {"action": "NORMAL", "multiplier": 1.0, "reason": "normal history"}


def optimiser_allows_scan(scan):
    if not PROFIT_OPTIMIZER_ENABLED:
        return True, "optimiser off"
    symbol = scan.get("symbol", "")
    confidence = float(scan.get("confidence", 0.0))
    if confidence < OPTIMIZER_MIN_CONFIDENCE:
        return False, f"confidence {confidence:.2f} below optimiser {OPTIMIZER_MIN_CONFIDENCE:.2f}"
    decision = auto_improve_decision(symbol)
    if decision["action"] == "BLACKLIST":
        return False, f"auto-blacklisted: {decision['reason']}"
    blocked, reason = profit_guardrail_status()
    if blocked:
        return False, reason
    return True, decision["reason"]


def optimiser_position_multiplier(symbol):
    return float(auto_improve_decision(symbol).get("multiplier", 1.0))


def optimiser_payload():
    blocked, reason = profit_guardrail_status()
    return {
        "enabled": PROFIT_OPTIMIZER_ENABLED,
        "autoImproveEnabled": AUTO_IMPROVE_ENABLED,
        "autoUniverseEnabled": AUTO_UNIVERSE_ENABLED,
        "autoUniverseEnabled": AUTO_UNIVERSE_ENABLED,
        "buyBlocked": blocked,
        "blockReason": reason,
        "dailyProfitTarget": DAILY_PROFIT_TARGET,
        "dailyLossLimit": DAILY_LOSS_LIMIT_OPTIMIZER,
        "todayRealisedPnl": today_realised_pnl(),
        "todayRealisedPnlGbp": today_realised_pnl_gbp(),
        "optimizedStopLoss": OPTIMIZED_STOP_LOSS,
        "optimizedTrailStart": OPTIMIZED_TRAIL_START,
        "optimizedTrailGiveback": OPTIMIZED_TRAIL_GIVEBACK,
        "autoBoostMultiplier": AUTO_BOOST_MULTIPLIER,
        "autoReduceMultiplier": AUTO_REDUCE_MULTIPLIER,
    }



# =========================
# WEEKLY AUTO UNIVERSE ROTATION
# =========================
def week_start_str(dt=None):
    dt = dt or datetime.now(UTC)
    monday = dt - timedelta(days=dt.weekday())
    return monday.strftime("%Y-%m-%d")


def get_last_universe_refresh():
    if not SQLITE_ENABLED:
        return None
    try:
        init_db()
        conn = db_connect()
        row = conn.execute("""
            SELECT refreshed_at FROM universe_refresh_log
            ORDER BY refreshed_at DESC
            LIMIT 1
        """).fetchone()
        conn.close()
        return row["refreshed_at"] if row else None
    except Exception:
        return None


def get_weekly_universe_from_db(week_start=None):
    if not SQLITE_ENABLED:
        return []
    week_start = week_start or week_start_str()
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute("""
            SELECT symbol, score, reason, status
            FROM weekly_universe
            WHERE week_start = ? AND status = 'active'
            ORDER BY score DESC
        """, (week_start,)).fetchall()
        conn.close()
        return [
            {"symbol": r["symbol"], "score": r["score"], "reason": r["reason"], "status": r["status"]}
            for r in rows
        ]
    except Exception as e:
        print(f"WEEKLY UNIVERSE READ ERROR: {e}")
        return []


def save_weekly_universe(rows, reason="weekly refresh"):
    if not SQLITE_ENABLED:
        return
    week = week_start_str()
    init_db()
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("UPDATE weekly_universe SET status='removed' WHERE week_start=?", (week,))

    for r in rows:
        cur.execute("""
            INSERT OR REPLACE INTO weekly_universe (week_start, symbol, score, reason, status)
            VALUES (?, ?, ?, ?, 'active')
        """, (week, r["symbol"], float(r.get("score") or 0), r.get("reason", "")))

    cur.execute("""
        INSERT INTO universe_refresh_log (refreshed_at, week_start, symbols, reason)
        VALUES (?, ?, ?, ?)
    """, (
        datetime.now(UTC).isoformat(),
        week,
        ",".join([r["symbol"] for r in rows]),
        reason,
    ))
    conn.commit()
    conn.close()


def should_refresh_weekly_universe(force=False):
    if force:
        return True
    if not AUTO_UNIVERSE_ENABLED:
        return False
    if not get_weekly_universe_from_db():
        return True

    last = get_last_universe_refresh()
    if not last:
        return True

    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        hours = (datetime.now(UTC) - last_dt).total_seconds() / 3600
        if hours < AUTO_UNIVERSE_MIN_HOURS_BETWEEN_REFRESH:
            return False
    except Exception:
        pass

    return datetime.now(UTC).weekday() == AUTO_UNIVERSE_REFRESH_DAY


def universe_rows_from_stock_memory():
    """
    Build a visible top-12 watchlist directly from the already-working stock memory.
    This is intentionally based on closed-trade performance so the panel always lines up
    with what the user sees in Stock Memory.
    """
    rows = []

    try:
        memory = stock_memory_from_closed_trades()
    except Exception:
        try:
            memory = stock_memory_from_db()
        except Exception:
            memory = []

    for m in memory:
        symbol = str(m.get("symbol", "")).upper()
        if not symbol:
            continue

        trades = int(m.get("trades") or 0)
        win_rate = float(m.get("winRate") or 0.0)
        avg_pnl = float(m.get("avgPnl") or 0.0)
        total_pnl = float(m.get("totalPnl") or 0.0)
        trust = str(m.get("trust") or "NEW")

        # Balanced score: rewards enough history, high win-rate, positive average PnL,
        # and good total PnL. Penalises weak performers.
        score = 0.0
        score += min(trades, 20) * 0.6
        score += win_rate * 12.0
        score += avg_pnl * 3.0
        score += max(-10.0, min(10.0, total_pnl)) * 0.5

        if trust.upper() == "GOOD":
            score += 5.0
        elif trust.upper() == "BAD":
            score -= 8.0

        reason = (
            f"trust {trust} | trades={trades} | "
            f"winRate={win_rate*100:.2f}% | avgPnL=${avg_pnl:.2f} | totalPnL=${total_pnl:.2f}"
        )

        rows.append({
            "symbol": symbol,
            "score": round(score, 4),
            "reason": reason,
            "status": "active",
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def score_candidate_symbol(symbol):
    """
    Fallback/new-candidate scoring for symbols not yet in stock memory.
    """
    symbol = symbol.upper()
    score = 1.0
    reasons = ["candidate pool"]

    try:
        q = get_quote(symbol)
        price = float(q["mid"])
        spread = float(q["spread"])

        if 1 <= price <= 800:
            score += 2.0
            reasons.append(f"price ok ${price:.2f}")
        else:
            score -= 10.0
            reasons.append(f"price out of range ${price:.2f}")

        if spread <= 0.02:
            score += max(0.0, 4.0 - spread * 200)
            reasons.append(f"spread ok {spread:.4f}")
        else:
            score -= 5.0
            reasons.append(f"spread wide {spread:.4f}")
    except Exception:
        score -= 2.0
        reasons.append("quote unavailable")

    try:
        qty, _ = get_position(symbol)
        if qty > DUST_THRESHOLD:
            score += 8.0
            reasons.append("currently held")
    except Exception:
        pass

    return {"symbol": symbol, "score": round(score, 4), "reason": " | ".join(reasons), "status": "active"}


def build_weekly_universe(force=False):
    global current_universe

    if not AUTO_UNIVERSE_ENABLED:
        return {"ok": False, "message": "Auto universe disabled", "symbols": current_universe}

    if not should_refresh_weekly_universe(force=force):
        active = get_weekly_universe_from_db()
        if active:
            current_universe = [r["symbol"] for r in active]
            for s in current_universe:
                ensure_symbol_state(s, custom=s in custom_symbols)
            return {"ok": True, "message": "Weekly universe already fresh", "symbols": current_universe, "rows": active}

    rows = universe_rows_from_stock_memory()

    # Add currently held symbols so open positions don't disappear from management.
    held_rows = []
    try:
        for p in get_all_positions():
            symbol = str(p.get("symbol", "")).upper()
            if symbol and symbol not in [r["symbol"] for r in rows]:
                held_rows.append({
                    "symbol": symbol,
                    "score": 20.0,
                    "reason": "currently held position",
                    "status": "active",
                })
    except Exception:
        pass

    combined = held_rows + rows

    # Fill empty slots with candidate pool.
    existing = {r["symbol"] for r in combined}
    for symbol in AUTO_UNIVERSE_CANDIDATE_POOL:
        if len(combined) >= AUTO_UNIVERSE_SIZE * 2:
            break
        if symbol not in existing:
            combined.append(score_candidate_symbol(symbol))
            existing.add(symbol)

    combined.sort(key=lambda r: r["score"], reverse=True)

    chosen = []
    seen = set()
    for r in combined:
        if len(chosen) >= AUTO_UNIVERSE_SIZE:
            break
        if r["symbol"] in seen:
            continue
        chosen.append(r)
        seen.add(r["symbol"])

    if not chosen:
        chosen = [{"symbol": s, "score": 0, "reason": "fallback safe universe", "status": "active"} for s in SAFE_UNIVERSE[:AUTO_UNIVERSE_SIZE]]

    save_weekly_universe(chosen, "forced refresh" if force else "weekly refresh")
    current_universe = [r["symbol"] for r in chosen]

    for s in current_universe:
        ensure_symbol_state(s, custom=s in custom_symbols)

    return {
        "ok": True,
        "message": f"Weekly universe updated with {len(current_universe)} symbols",
        "symbols": current_universe,
        "rows": chosen,
    }


def auto_universe_payload():
    active = get_weekly_universe_from_db()

    # If DB has not been populated yet but stock memory exists, show live preview.
    if not active:
        preview = universe_rows_from_stock_memory()[:AUTO_UNIVERSE_SIZE]
        active = preview

    return {
        "enabled": AUTO_UNIVERSE_ENABLED,
        "size": AUTO_UNIVERSE_SIZE,
        "weekStart": week_start_str(),
        "activeSymbols": [r["symbol"] for r in active] if active else list(current_universe),
        "rows": active,
        "lastRefresh": get_last_universe_refresh(),
        "candidatePoolSize": len(AUTO_UNIVERSE_CANDIDATE_POOL),
        "keepWinners": True,
    }




def weekly_universe_public():
    return auto_universe_payload()

# =========================
# STATUS
# =========================
def update_equity_curve(account):
    equity_usd = float(account.equity)
    point = {"t": now_chart_time(), "value": equity_usd, "valueGbp": money_gbp(equity_usd)}
    if not equity_curve or equity_curve[-1]["value"] != point["value"]:
        equity_curve.append(point)
    if len(equity_curve) > 240:
        equity_curve.pop(0)


def build_status_payload(bot_name, scans):
    account = get_account()
    update_equity_curve(account)
    positions = get_all_positions()
    active = positions[0] if positions else None
    daily_pnl = get_daily_pnl()
    blocked, risk_reason = risk_blocked()
    market_status = get_market_status_payload()
    locked_symbols = sorted([s for s, d in locked_today.items() if d == today_str()])

    return {
        "id": "rebuilt-sniper-live",
        "name": bot_name,
        "paperMode": PAPER,
        "botEnabled": bot_enabled,
        "manualOverride": manual_override,
        "emergencyStop": emergency_stop,
        "riskBlocked": blocked,
        "riskReason": risk_reason,
        "mode": "SNIPER_CONFIDENCE_MEMORY_TIMELINE_GBP",
        "market": market_status,
        "fx": fx_payload(),
        "autoUniverse": auto_universe_payload(),
        "dynamicMarketScanner": dynamic_market_scanner_payload() if "dynamic_market_scanner_payload" in globals() else {},
        "analytics": analytics_payload(),
        "optimiser": optimiser_payload(),
        "strictOneCyclePerStockPerDay": STRICT_ONE_CYCLE_PER_STOCK_PER_DAY,
        "allowCustomBuy": ALLOW_CUSTOM_BUY,
        "profitModeEnabled": PROFIT_MODE_ENABLED,
        "rotationModeEnabled": ROTATION_MODE_ENABLED,
        "pdtAwareModeEnabled": PDT_AWARE_MODE_ENABLED,
        "sniperModeEnabled": SNIPER_MODE_ENABLED,
        "confidenceSizingEnabled": CONFIDENCE_SIZING_ENABLED,
        "stockMemoryEnabled": STOCK_MEMORY_ENABLED,
        "profitOptimizerEnabled": PROFIT_OPTIMIZER_ENABLED,
        "analyticsEnabled": ANALYTICS_ENABLED,
        "autoImproveEnabled": AUTO_IMPROVE_ENABLED,
        "autoUniverseEnabled": AUTO_UNIVERSE_ENABLED,
        "autoUniverseEnabled": AUTO_UNIVERSE_ENABLED,
        "fastExitModeEnabled": FAST_EXIT_MODE_ENABLED,
        "partialProfitEnabled": PARTIAL_PROFIT_ENABLED,
        "partialProfitTriggerPct": PARTIAL_PROFIT_TRIGGER_PCT,
        "partialProfitSellPct": PARTIAL_PROFIT_SELL_PCT,
        "fastStopLossPct": FAST_STOP_LOSS_PCT,
        "stallExitEnabled": STALL_EXIT_ENABLED,
        "stallExitAfterMinutes": STALL_EXIT_AFTER_MINUTES,
        "aPlusGateEnabled": A_PLUS_GATE_ENABLED,
        "aPlusMinConfidence": A_PLUS_MIN_CONFIDENCE,
        "aPlusMinQuality": A_PLUS_MIN_QUALITY,
        "tempBlacklist": temp_blacklist,
        "todayBuyCount": today_buy_count(),
        "maxNewBuysPerDayPdtAware": MAX_NEW_BUYS_PER_DAY_PDT_AWARE,
        "lockedSymbolsToday": locked_symbols,
        "customSymbols": sorted(list(custom_symbols.keys())),
        "maxPositions": MAX_POSITIONS,
        "newPositionNotional": calculate_new_position_notional(),
        "allowedNewPositions": allowed_new_position_count(),
        "universe": list(current_universe),
        "config": {
            "checkInterval": CHECK_INTERVAL,
            "maxPositions": MAX_POSITIONS,
            "targetPositionValuePct": TARGET_POSITION_VALUE_PCT,
            "maxPositionValuePct": MAX_POSITION_VALUE_PCT,
            "stopLoss": STOP_LOSS,
            "trailStart": TRAIL_START,
            "trailGiveback": TRAIL_GIVEBACK,
            "fastExitModeEnabled": FAST_EXIT_MODE_ENABLED,
            "partialProfitTriggerPct": PARTIAL_PROFIT_TRIGGER_PCT,
            "partialProfitSellPct": PARTIAL_PROFIT_SELL_PCT,
            "fastStopLossPct": FAST_STOP_LOSS_PCT,
            "stallExitAfterMinutes": STALL_EXIT_AFTER_MINUTES,
            "sniperMinConfidence": SNIPER_MIN_CONFIDENCE,
            "sniperMinQuality": SNIPER_MIN_QUALITY,
        },
        "account": {
            "equity": float(account.equity),
            "equityGbp": money_gbp(float(account.equity)),
            "buyingPower": float(account.buying_power),
            "buyingPowerGbp": money_gbp(float(account.buying_power)),
            "cash": float(account.cash),
            "cashGbp": money_gbp(float(account.cash)),
            "pnlDay": float(daily_pnl),
            "pnlDayGbp": money_gbp(float(daily_pnl)),
        },
        "activePosition": {
            "symbol": active["symbol"] if active else "—",
            "qty": float(active["qty"]) if active else 0.0,
            "entry": float(active["entry"]) if active else 0.0,
            "price": float(active["price"]) if active else 0.0,
            "pnl": float(active["pnl"]) if active else 0.0,
            "pnlGbp": money_gbp(float(active["pnl"])) if active else 0.0,
            "pnlPct": float(active["pnlPct"]) if active else 0.0,
            "trailingActive": bool(active["trailingActive"]) if active else False,
            "trailStartPrice": float(active["trailStartPrice"]) if active else 0.0,
            "trailFloor": float(active["trailFloor"]) if active else 0.0,
        },
        "positions": positions,
        "scans": [
            {
                "symbol": s["symbol"], "price": float(s["price"]), "ref": float(s["ref"]),
                "trigger": float(s["buy_trigger"]), "spread": float(s["spread"]),
                "qty": float(s["qty"]), "score": float(s["score"]),
                "pullback": float(s["pullback"]), "shortMomentum": float(s["short_momentum"]),
                "qualityScore": float(s["quality_score"]), "readyToBuy": bool(s["ready_to_buy"]),
                "lockedToday": bool(s["locked_today"]), "custom": bool(s.get("custom", False)),
                "priceCurve": s.get("price_curve", []), "confidence": float(s.get("confidence", 0.0)),
                "confidenceLabel": s.get("confidence_label", "LOW"),
                "sniperPass": bool(s.get("sniper_pass", False)),
                "sniperReason": s.get("sniper_reason", ""),
                "aPlusPass": bool(s.get("a_plus_pass", False)),
                "aPlusReason": s.get("a_plus_reason", ""),
                "optimiserDecision": auto_improve_decision(s["symbol"]),
            } for s in scans
        ],
        "banking": banking_payload(),
        "logs": [
            f"MODE | SNIPER_CONFIDENCE_MEMORY_TIMELINE | max_positions={MAX_POSITIONS} | allowed_new={allowed_new_position_count()}",
            f"SNIPER | enabled={SNIPER_MODE_ENABLED} | confidence_sizing={CONFIDENCE_SIZING_ENABLED} | memory={STOCK_MEMORY_ENABLED} | timeline={len(trade_history)}",
            f"FX | USDGBP={get_usd_to_gbp_rate():.4f} | source={fx_cache.get('source', 'fallback')}",
            f"DB | sqlite={SQLITE_ENABLED} | raw_trades={db_summary_payload().get('totalTrades', 0)} | closed={closed_trade_summary_payload().get('closedTrades', 0)} | pnl_gbp={closed_trade_summary_payload().get('totalPnlGbp', 0):.2f}",
            f"BACKFILL | chunk={BACKFILL_CHUNK_SIZE} | max_pages={BACKFILL_MAX_PAGES}",
            f"OPTIMIZER | enabled={PROFIT_OPTIMIZER_ENABLED} | today_realised={today_realised_pnl():.2f} | block={profit_guardrail_status()[1] or 'none'}",
            f"ANALYTICS | profit_factor={analytics_payload().get('profitFactor', 0):.2f} | avg_win={analytics_payload().get('averageWin', 0):.2f} | avg_loss={analytics_payload().get('averageLoss', 0):.2f}",
            f"A+ GATE | enabled={A_PLUS_GATE_ENABLED} | min_conf={A_PLUS_MIN_CONFIDENCE} | min_quality={A_PLUS_MIN_QUALITY} | blacklist={len(temp_blacklist)}",
            f"PDT AWARE | enabled={PDT_AWARE_MODE_ENABLED} | today_buys={today_buy_count()}/{MAX_NEW_BUYS_PER_DAY_PDT_AWARE} | warnings={len(pdt_warning_events)}",
            f"FAST EXIT | enabled={FAST_EXIT_MODE_ENABLED} | partial={PARTIAL_PROFIT_TRIGGER_PCT}%/{int(PARTIAL_PROFIT_SELL_PCT*100)}% | stop={FAST_STOP_LOSS_PCT}% | stall={STALL_EXIT_AFTER_MINUTES}m",
            f"MARKET | {market_status.get('label', 'UNKNOWN')}",
            f"ACCOUNT | equity={float(account.equity):.2f} | buying_power={float(account.buying_power):.2f}",
            f"POSITIONS | {len(positions)}",
            f"LOCKOUT | locked_today={', '.join(locked_symbols) if locked_symbols else 'none'}",
        ],
        "trades": trade_events[-50:],
        "tradeTimeline": trades_from_db(1000),
        "closedTrades": closed_trades_from_db(1000),
        "stockMemory": stock_memory_from_closed_trades(),
        "dbSummary": {**db_summary_payload(), **closed_trade_summary_payload()},
        "equityCurve": equity_curve[-240:],
        "alpacaRejectionEvents": alpaca_rejection_events[-50:],
        "pdtWarningEvents": pdt_warning_events[-50:],
    }


def update_status(bot_name, scans):
    latest_status.clear()
    latest_status.update(build_status_payload(bot_name, scans))


# =========================
# ROUTES
# =========================

@app.get("/debug-orders")
def debug_orders():
    try:
        req = GetOrdersRequest(
            status=get_query_order_status_all(),
            limit=10,
            direction="desc",
        )
        orders = trading_client.get_orders(filter=req)
        sample = []
        for o in orders[:10]:
            sample.append({
                "id": str(getattr(o, "id", "")),
                "symbol": str(getattr(o, "symbol", "")),
                "side": str(getattr(o, "side", "")),
                "status": str(getattr(o, "status", "")),
                "filled_qty": str(getattr(o, "filled_qty", "")),
                "filled_avg_price": str(getattr(o, "filled_avg_price", "")),
                "submitted_at": str(getattr(o, "submitted_at", "")),
                "filled_at": str(getattr(o, "filled_at", "")),
            })
        return {"ok": True, "count": len(orders), "sample": sample}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/")
def root():
    return {"message": "Rebuilt Sniper Profit Bot running", "status": "/status", "paperMode": PAPER}


@app.get("/status")
def get_status():
    latest_status["botVersion"] = "v1.1-strict-profit-mode"
    try:
        if "merge_manual_picks_into_auto_universe" in globals():
            return merge_manual_picks_into_auto_universe(latest_status)
    except Exception as e:
        print(f"STATUS MANUAL PICK MERGE ERROR: {e}")
    return latest_status


@app.post("/pause")
def pause_bot(request: Request):
    verify_api_key(request)
    global bot_enabled
    bot_enabled = False
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot paused"}


@app.post("/resume")
def resume_bot(request: Request):
    verify_api_key(request)
    global bot_enabled, emergency_stop
    bot_enabled = True
    emergency_stop = False
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot resumed"}


@app.post("/manual-override/on")
def manual_override_on(request: Request):
    verify_api_key(request)
    global manual_override
    manual_override = True
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Manual override ON. Auto-buy paused."}


@app.post("/manual-override/off")
def manual_override_off(request: Request):
    verify_api_key(request)
    global manual_override
    manual_override = False
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Manual override OFF. Auto-buy active."}


@app.post("/manual-buy")
def manual_buy(request: Request):
    verify_api_key(request)
    with bot_lock:
        if not trading_client.get_clock().is_open:
            return {"ok": False, "message": "Market closed"}
        result = money_mode_buy(latest_scans, manual=True)
        update_status(BOT_NAME, latest_scans)
        return {"ok": True, "message": result}


@app.post("/custom-buy/{symbol}")
def custom_buy(symbol: str, request: Request):
    verify_api_key(request)
    with bot_lock:
        result = buy_custom_symbol(symbol)
        update_status(BOT_NAME, latest_scans)
        return result


@app.post("/manual-sell")
def manual_sell(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = close_worst_or_largest_position(reason="MANUAL SELL")
        update_status(BOT_NAME, latest_scans)
        return result


@app.post("/sell/{symbol}")
def sell_symbol(symbol: str, request: Request):
    verify_api_key(request)
    with bot_lock:
        result = close_position_by_symbol(symbol.upper(), reason="MANUAL SYMBOL SELL")
        update_status(BOT_NAME, latest_scans)
        return result


@app.post("/emergency-sell")
def emergency_sell(request: Request):
    verify_api_key(request)
    global emergency_stop, bot_enabled
    with bot_lock:
        emergency_stop = True
        bot_enabled = False
        result = close_all_positions(reason="EMERGENCY SELL")
        update_status(BOT_NAME, latest_scans)
        return {**result, "emergencyStop": True, "botEnabled": False}




@app.post("/rebuild-closed-trades")
def rebuild_closed_trades(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = rebuild_closed_trades_from_orders()
        update_status(BOT_NAME, latest_scans)
        return result



@app.post("/backfill-trades-limited")
def backfill_trades_limited(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = backfill_trades_from_alpaca()
        update_status(BOT_NAME, latest_scans)
        return result





def refresh_universe(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = build_weekly_universe(force=True)
        update_status(BOT_NAME, latest_scans)
        return result


@app.post("/backfill-trades")
def backfill_trades(request: Request):
    verify_api_key(request)
    with bot_lock:
        result = backfill_trades_from_alpaca_full()
        update_status(BOT_NAME, latest_scans)
        return result


# =========================
# LOOP
# =========================
def run_bot_loop():
    print("Rebuilt Sniper Profit Bot started...")
    init_db()
    load_persistent_state()
    refresh_universe_if_needed(force=True)
    reset_daily_flags_if_needed()
    update_status(BOT_NAME, [])

    while True:
        try:
            with bot_lock:
                reset_daily_flags_if_needed()
                cleanup_temp_blacklist()
                try:
                    refresh_dynamic_market_candidates_if_needed()
                except Exception as e:
                    print(f"DYNAMIC SCANNER LOOP ERROR: {e}")
                refresh_universe_if_needed()
                clock = trading_client.get_clock()

                if not clock.is_open:
                    print("Market closed. Waiting...")
                    update_status(BOT_NAME, latest_scans)
                    time.sleep(CHECK_INTERVAL)
                    continue

                scans = []
                for symbol in current_universe:
                    try:
                        scan = compute_scan(symbol)
                        scans.append(scan)
                        print(f"{symbol} | price={scan['price']:.2f} | quality={scan['quality_score']:.4f} | confidence={scan['confidence']:.2f} | sniper={scan['sniper_pass']}")
                    except Exception as e:
                        print(f"SCAN ERROR {symbol}: {e}")

                latest_scans.clear()
                latest_scans.extend(scans)

                if bot_enabled and not emergency_stop:
                    manage_money_mode_positions()
                    if PROFIT_MODE_ENABLED and ROTATION_MODE_ENABLED:
                        rr = maybe_rotate_weakest_into_best(scans)
                        if rr:
                            print(rr)
                    if not manual_override:
                        result = money_mode_buy(scans, manual=False)
                        if result:
                            print(result)
                update_status(BOT_NAME, scans)

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(10)


@app.on_event("startup")
def startup_event():
    global bot_thread_started
    if bot_thread_started:
        return
    bot_thread_started = True
    threading.Thread(target=run_bot_loop, daemon=True).start()



# =========================
# V1.0 PRODUCTION STABLE ADDONS
# =========================

BOT_VERSION = "v1.1-strict-profit-mode"
BOT_VERSION_NOTES = {
    "version": BOT_VERSION,
    "name": "TradeBot v1.0 Production Stable",
    "sameDayTrading": True,
    "sellThenLockUntilNextDay": True,
    "manualUniversePins": True,
    "weeklyUniverseRefresh": True,
    "gbpFirstReports": True,
    "pdtAware": True,
}

@app.get("/version")
def version():
    return BOT_VERSION_NOTES

# ---------- baseline reporting ----------
BASELINE_FILE = os.path.join("backend", "state", "equity_baseline.json")

def _safe_num(v, default=0.0):
    try:
        return float(v or default)
    except Exception:
        return float(default)

def load_equity_baseline() -> float:
    try:
        if os.path.exists(BASELINE_FILE):
            with open(BASELINE_FILE, "r", encoding="utf-8") as f:
                return float(json.load(f).get("baseline", 0) or 0)
    except Exception as e:
        print(f"BASELINE LOAD ERROR: {e}")
    return 0.0

def save_equity_baseline(value: float) -> None:
    try:
        os.makedirs(os.path.dirname(BASELINE_FILE), exist_ok=True)
        with open(BASELINE_FILE, "w", encoding="utf-8") as f:
            json.dump({"baseline": float(value or 0), "resetAt": datetime.now(UTC).isoformat()}, f, indent=2)
    except Exception as e:
        print(f"BASELINE SAVE ERROR: {e}")

@app.post("/reset-baseline")
def reset_baseline(request: Request):
    verify_api_key(request)
    try:
        equity = _safe_num(latest_status.get("account", {}).get("equity", 0))
        save_equity_baseline(equity)
        return {"ok": True, "message": f"Baseline reset to ${equity:.2f}", "baseline": equity}
    except Exception as e:
        return {"ok": False, "message": str(e)}

@app.get("/baseline")
def get_baseline():
    return {"ok": True, "baseline": load_equity_baseline()}

@app.get("/reports")
def reports():
    status = latest_status if isinstance(latest_status, dict) else {}
    account = status.get("account") or {}
    db = status.get("dbSummary") or {}
    equity = _safe_num(account.get("equity"))
    equity_gbp = _safe_num(account.get("equityGbp"))
    total_withdrawn = _safe_num(globals().get("TOTAL_WITHDRAWN_USD", 0))
    baseline = load_equity_baseline()
    total_deposited = baseline if baseline > 0 else _safe_num(globals().get("TOTAL_DEPOSITED_USD", 0))
    deposit_source = "reset-baseline" if baseline > 0 else "env"
    if total_deposited <= 0:
        total_deposited = equity
        deposit_source = "equity-baseline"
    total_gain_loss = equity + total_withdrawn - total_deposited
    closed = status.get("closedTrades") or []
    timeline = status.get("tradeTimeline") or status.get("equityCurve") or []
    equity_history = []
    for i, e in enumerate(timeline if isinstance(timeline, list) else []):
        if not isinstance(e, dict):
            continue
        equity_history.append({
            "idx": i,
            "time": e.get("time") or e.get("timestamp") or e.get("t") or "",
            "symbol": e.get("symbol") or "",
            "side": e.get("side") or "",
            "equity": _safe_num(e.get("equity") or e.get("value")),
            "equityGbp": _safe_num(e.get("equityGbp") or e.get("valueGbp")),
            "pnl": _safe_num(e.get("pnl")),
            "pnlGbp": _safe_num(e.get("pnlGbp")),
            "pnlPct": _safe_num(e.get("pnlPct")),
            "reason": e.get("reason") or "",
        })
    return {
        "ok": True,
        "depositSource": deposit_source,
        "totalDeposited": total_deposited,
        "totalWithdrawn": total_withdrawn,
        "currentEquity": equity,
        "currentEquityGbp": equity_gbp,
        "totalGainLoss": total_gain_loss,
        "earnedSinceDeposit": max(total_gain_loss, 0.0),
        "lostSinceDeposit": abs(min(total_gain_loss, 0.0)),
        "dayPnl": _safe_num(account.get("pnlDay")),
        "realisedNet": _safe_num(db.get("totalPnl")),
        "closedTrades": closed[-200:] if isinstance(closed, list) else [],
        "equityHistory": equity_history[-500:],
        "winRate": _safe_num(db.get("winRate")) * 100.0,
        "totalTrades": int(_safe_num(db.get("totalTrades"))),
    }

# ---------- manual universe pins ----------
MANUAL_UNIVERSE_FILE = os.path.join("backend", "state", "manual_universe_picks.json")

def load_manual_universe_picks() -> List[str]:
    try:
        if os.path.exists(MANUAL_UNIVERSE_FILE):
            with open(MANUAL_UNIVERSE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return sorted({str(x).upper().strip() for x in data if str(x).strip()})
    except Exception as e:
        print(f"MANUAL UNIVERSE LOAD ERROR: {e}")
    return []

def save_manual_universe_picks(symbols: List[str]) -> None:
    try:
        os.makedirs(os.path.dirname(MANUAL_UNIVERSE_FILE), exist_ok=True)
        clean = sorted({str(x).upper().strip() for x in symbols if str(x).strip()})
        with open(MANUAL_UNIVERSE_FILE, "w", encoding="utf-8") as f:
            json.dump(clean, f, indent=2)
    except Exception as e:
        print(f"MANUAL UNIVERSE SAVE ERROR: {e}")

def add_manual_universe_pick(symbol: str) -> List[str]:
    sym = symbol.upper().strip()
    picks = load_manual_universe_picks()
    if sym and sym not in picks:
        picks.append(sym)
    save_manual_universe_picks(picks)
    return load_manual_universe_picks()

def remove_manual_universe_pick(symbol: str) -> List[str]:
    sym = symbol.upper().strip()
    picks = [x for x in load_manual_universe_picks() if x != sym]
    save_manual_universe_picks(picks)
    return picks

def manual_pick_row(symbol: str) -> Dict[str, Any]:
    return {"symbol": symbol.upper(), "score": 99.0, "reason": "manual pick | pinned to universe", "manualPick": True, "status": "active"}

def apply_manual_picks_to_current_universe() -> None:
    try:
        for sym in load_manual_universe_picks():
            add_symbol_to_universe(sym, custom=True)
    except Exception as e:
        print(f"APPLY MANUAL PICKS ERROR: {e}")

def merge_manual_picks_into_auto_universe(status_obj: Dict[str, Any]) -> Dict[str, Any]:
    try:
        picks = load_manual_universe_picks()
        apply_manual_picks_to_current_universe()
        status_obj["manualUniversePicks"] = picks
        au = status_obj.setdefault("autoUniverse", {})
        rows = au.setdefault("rows", [])
        active = au.setdefault("activeSymbols", [])
        existing_rows = {str(r.get("symbol", "")).upper() for r in rows if isinstance(r, dict)}
        existing_active = {str(x).upper() for x in active}
        for sym in reversed(picks):
            if sym not in existing_rows:
                rows.insert(0, manual_pick_row(sym))
            if sym not in existing_active:
                active.insert(0, sym)
        au["rows"] = rows
        au["activeSymbols"] = active
        au["size"] = max(int(au.get("size") or 0), len(active))
        au["manualPickCount"] = len(picks)
    except Exception as e:
        print(f"MERGE MANUAL PICKS ERROR: {e}")
    return status_obj

@app.get("/manual-universe")
def api_manual_universe():
    return {"ok": True, "symbols": load_manual_universe_picks()}



def touch_quick_status(**kwargs):
    """Small safe status updater used by manual-universe/search buttons.
    Keeps UI feedback fields current without forcing a full status rebuild.
    """
    try:
        for key, value in kwargs.items():
            latest_status[key] = value
        latest_status["quickStatusUpdatedAt"] = datetime.now(UTC).isoformat()
        return True
    except Exception as e:
        print(f"TOUCH QUICK STATUS ERROR: {e}")
        return False

@app.post("/add-to-universe/{symbol}")
def add_to_universe(symbol: str, request: Request):
    verify_api_key(request)
    sym = symbol.upper().strip()
    try:
        picks = add_manual_universe_pick(sym)
        add_symbol_to_universe(sym, custom=True)
        latest_status.setdefault("autoUniverse", {})
        latest_status["autoUniverse"].setdefault("rows", [])
        latest_status["autoUniverse"].setdefault("activeSymbols", [])
        merge_manual_picks_into_auto_universe(latest_status)
        touch_quick_status(lastAction=f"{sym} added and pinned to universe", lastActionAt=datetime.now(UTC).isoformat())
        return {"ok": True, "message": f"{sym} added and pinned to universe", "symbols": picks, "manualPick": True}
    except Exception as e:
        return {"ok": False, "message": f"Could not add {sym}: {e}"}

@app.post("/remove-from-universe/{symbol}")
def api_remove_from_universe(symbol: str, request: Request):
    verify_api_key(request)
    picks = remove_manual_universe_pick(symbol)
    try:
        sym = symbol.upper().strip()
        if sym in current_universe:
            current_universe.remove(sym)
        custom_symbols.pop(sym, None)
    except Exception:
        pass
    update_status(BOT_NAME, latest_scans)
    merge_manual_picks_into_auto_universe(latest_status)
    return {"ok": True, "message": f"{symbol.upper()} removed from manual picks", "symbols": picks}

# Wrap weekly universe builder so pinned picks survive refreshes and are tradable.
_ORIGINAL_BUILD_WEEKLY_UNIVERSE = build_weekly_universe

def build_weekly_universe(force=False):
    result = _ORIGINAL_BUILD_WEEKLY_UNIVERSE(force=force)
    apply_manual_picks_to_current_universe()
    try:
        picks = load_manual_universe_picks()
        rows = result.setdefault("rows", []) if isinstance(result, dict) else []
        symbols = result.setdefault("symbols", []) if isinstance(result, dict) else []
        existing = {str(r.get("symbol", "")).upper() for r in rows if isinstance(r, dict)}
        for sym in reversed(picks):
            if sym not in existing:
                rows.insert(0, manual_pick_row(sym))
            if sym not in symbols:
                symbols.insert(0, sym)
    except Exception as e:
        print(f"BUILD WEEKLY MANUAL MERGE ERROR: {e}")
    return result

# ---------- search preview ----------
SEARCH_PREVIEW_HISTORY: Dict[str, List[Dict[str, Any]]] = {}

def _stock_name_guess(symbol: str) -> str:
    names = {"AAPL":"Apple","MSFT":"Microsoft","NVDA":"NVIDIA","AMD":"Advanced Micro Devices","AMZN":"Amazon","META":"Meta Platforms","GOOGL":"Alphabet","GOOG":"Alphabet","TSLA":"Tesla","INTC":"Intel","NFLX":"Netflix","CRM":"Salesforce","ORCL":"Oracle","ADBE":"Adobe","PYPL":"PayPal","UBER":"Uber","PLTR":"Palantir","SHOP":"Shopify","SNOW":"Snowflake","NET":"Cloudflare","MDB":"MongoDB","MU":"Micron","LAC":"Lithium Americas","LCID":"Lucid","TTWO":"Take-Two Interactive","EA":"Electronic Arts","RBLX":"Roblox","U":"Unity Software"}
    return names.get(symbol.upper(), symbol.upper())

def _stock_search_universe() -> List[str]:
    symbols = []
    for name in ["current_universe", "SAFE_UNIVERSE", "TECH_UNIVERSE", "AUTO_UNIVERSE", "UNIVERSE"]:
        val = globals().get(name)
        if isinstance(val, list):
            symbols.extend([str(x).upper() for x in val])
    symbols.extend(load_manual_universe_picks())
    symbols.extend(["AAPL","MSFT","NVDA","AMD","AMZN","META","GOOGL","GOOG","TSLA","INTC","NFLX","CRM","ORCL","ADBE","PYPL","UBER","PLTR","SHOP","SNOW","NET","MDB","MU","LAC","LCID","AVGO","QCOM","TXN","NOW","DDOG","CRWD","PANW","ZS","TEAM","SQ","COIN","HOOD","RBLX","ROKU","DIS","TTWO","EA","U"])
    seen = []
    for s in symbols:
        s = str(s).upper().strip()
        if s and s not in seen:
            seen.append(s)
    return seen

def _search_fx_rate() -> float:
    try:
        return float(get_usd_to_gbp_rate())
    except Exception:
        return 0.7403

def _latest_quote_for_symbol(symbol: str) -> Dict[str, Any]:
    symbol = symbol.upper().strip()
    quote_price = bid = ask = spread = 0.0
    try:
        req = StockLatestQuoteRequest(symbol_or_symbols=[symbol])
        q = data_client.get_stock_latest_quote(req)
        quote = q.get(symbol) if isinstance(q, dict) else None
        if quote:
            bid = float(getattr(quote, "bid_price", 0) or 0)
            ask = float(getattr(quote, "ask_price", 0) or 0)
            quote_price = round((bid + ask) / 2, 4) if bid and ask else round(float(ask or bid or 0), 4)
            spread = round(ask - bid, 4) if ask and bid else 0.0
    except Exception as e:
        print(f"SEARCH QUOTE ERROR {symbol}: {e}")
    if quote_price <= 0:
        try:
            for s in latest_scans:
                if str(s.get("symbol", "")).upper() == symbol:
                    quote_price = float(s.get("price") or 0)
                    break
        except Exception:
            pass
    now = datetime.now(UTC).isoformat()
    hist = SEARCH_PREVIEW_HISTORY.setdefault(symbol, [])
    if quote_price > 0:
        hist.append({"t": now, "value": quote_price})
        del hist[:-80]
    prev = hist[0]["value"] if hist else quote_price
    change = quote_price - prev if quote_price and prev else 0.0
    change_pct = (change / prev * 100.0) if prev else 0.0
    fx = _search_fx_rate()
    return {"symbol": symbol, "name": _stock_name_guess(symbol), "price": quote_price, "priceGbp": round(quote_price * fx, 4), "bid": bid, "ask": ask, "spread": spread, "change": round(change, 4), "changePct": round(change_pct, 4), "history": hist, "inUniverse": symbol in [x.upper() for x in _stock_search_universe()]}

@app.get("/search-stocks")
def search_stocks(q: str = ""):
    query = (q or "").strip().upper()
    if not query:
        return {"ok": True, "query": q, "results": []}
    matches = []
    for sym in _stock_search_universe():
        name = _stock_name_guess(sym).upper()
        if query in sym or query in name:
            matches.append(sym)
        if len(matches) >= 8:
            break
    if re.fullmatch(r"[A-Z]{1,5}", query) and query not in matches:
        matches.insert(0, query)
    deduped = []
    for sym in matches:
        if sym not in deduped:
            deduped.append(sym)
    results = []
    for sym in deduped[:8]:
        qd = _latest_quote_for_symbol(sym)
        if qd.get("price", 0) > 0 or sym == query:
            results.append(qd)
    return {"ok": True, "query": q, "results": results}

@app.get("/stock-preview/{symbol}")
def stock_preview(symbol: str):
    return {"ok": True, "stock": _latest_quote_for_symbol(symbol)}




# =========================
# STRICTER PROFIT MODE v1.1
# =========================

STRICT_PROFIT_MODE = os.getenv("STRICT_PROFIT_MODE", "true").lower() == "true"
STRICT_STOP_LOSS_PCT = float(os.getenv("STRICT_STOP_LOSS_PCT", "-2.25"))
STRICT_TAKE_PROFIT_PCT = float(os.getenv("STRICT_TAKE_PROFIT_PCT", "1.25"))
STRICT_TRAIL_START_PCT = float(os.getenv("STRICT_TRAIL_START_PCT", "1.00"))
STRICT_TRAIL_DROP_PCT = float(os.getenv("STRICT_TRAIL_DROP_PCT", "0.45"))
STRICT_MAX_POSITIONS = int(os.getenv("STRICT_MAX_POSITIONS", "6"))
LOSER_COOLDOWN_DAYS = int(os.getenv("LOSER_COOLDOWN_DAYS", "3"))
LOSER_COOLDOWN_FILE = os.path.join("backend", "state", "loser_cooldown.json")

def _load_loser_cooldown() -> Dict[str, Any]:
    try:
        if os.path.exists(LOSER_COOLDOWN_FILE):
            with open(LOSER_COOLDOWN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"LOSER COOLDOWN LOAD ERROR: {e}")
    return {}

def _save_loser_cooldown(data: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(LOSER_COOLDOWN_FILE), exist_ok=True)
        with open(LOSER_COOLDOWN_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"LOSER COOLDOWN SAVE ERROR: {e}")

def add_loser_cooldown(symbol: str, pnl_pct: float = 0.0, reason: str = "loss") -> None:
    try:
        sym = symbol.upper().strip()
        until = (datetime.now(UTC) + timedelta(days=LOSER_COOLDOWN_DAYS)).date().isoformat()
        data = _load_loser_cooldown()
        data[sym] = {"until": until, "pnlPct": float(pnl_pct or 0), "reason": reason, "createdAt": datetime.now(UTC).isoformat()}
        _save_loser_cooldown(data)
        print(f"LOSER COOLDOWN | {sym} blocked until {until} | pnlPct={pnl_pct}")
    except Exception as e:
        print(f"ADD LOSER COOLDOWN ERROR: {e}")

def is_loser_cooldown(symbol: str) -> bool:
    try:
        sym = symbol.upper().strip()
        data = _load_loser_cooldown()
        row = data.get(sym)
        if not row:
            return False
        until = datetime.fromisoformat(row.get("until")).date()
        if datetime.now(UTC).date() <= until:
            return True
        data.pop(sym, None)
        _save_loser_cooldown(data)
    except Exception:
        return False
    return False

def strict_position_should_sell(symbol: str, entry_price: float, current_price: float, high_price: float = 0.0) -> Dict[str, Any]:
    try:
        if not STRICT_PROFIT_MODE:
            return {"sell": False, "reason": ""}
        entry = float(entry_price or 0)
        price = float(current_price or 0)
        high = float(high_price or price or 0)
        if entry <= 0 or price <= 0:
            return {"sell": False, "reason": ""}

        pnl_pct = ((price - entry) / entry) * 100.0
        high_pct = ((high - entry) / entry) * 100.0
        drop_from_high_pct = ((price - high) / high) * 100.0 if high > 0 else 0.0

        if pnl_pct <= STRICT_STOP_LOSS_PCT:
            add_loser_cooldown(symbol, pnl_pct, "strict-stop-loss")
            return {"sell": True, "reason": f"STRICT STOP LOSS {pnl_pct:.2f}%", "pnlPct": pnl_pct}

        if pnl_pct >= STRICT_TAKE_PROFIT_PCT:
            return {"sell": True, "reason": f"STRICT TAKE PROFIT {pnl_pct:.2f}%", "pnlPct": pnl_pct}

        if high_pct >= STRICT_TRAIL_START_PCT and drop_from_high_pct <= -abs(STRICT_TRAIL_DROP_PCT):
            return {"sell": True, "reason": f"STRICT TRAIL DROP {drop_from_high_pct:.2f}%", "pnlPct": pnl_pct}
    except Exception as e:
        print(f"STRICT SELL DECISION ERROR {symbol}: {e}")
    return {"sell": False, "reason": ""}

def strict_can_buy_symbol(symbol: str) -> Dict[str, Any]:
    try:
        if STRICT_PROFIT_MODE and is_loser_cooldown(symbol):
            return {"ok": False, "reason": f"{symbol.upper()} in loser cooldown"}
    except Exception as e:
        print(f"STRICT CAN BUY ERROR {symbol}: {e}")
    return {"ok": True, "reason": ""}

@app.get("/strict-mode")
def api_strict_mode():
    return {
        "ok": True,
        "version": "v1.1-strict-profit-mode",
        "strictProfitMode": STRICT_PROFIT_MODE,
        "stopLossPct": STRICT_STOP_LOSS_PCT,
        "takeProfitPct": STRICT_TAKE_PROFIT_PCT,
        "trailStartPct": STRICT_TRAIL_START_PCT,
        "trailDropPct": STRICT_TRAIL_DROP_PCT,
        "maxPositions": STRICT_MAX_POSITIONS,
        "loserCooldownDays": LOSER_COOLDOWN_DAYS,
        "loserCooldown": _load_loser_cooldown(),
    }

@app.post("/clear-loser-cooldown")
def api_clear_loser_cooldown(request: Request):
    verify_api_key(request)
    _save_loser_cooldown({})
    return {"ok": True, "message": "Loser cooldown cleared"}





# =========================
# DYNAMIC MARKET SCANNER v1.0
# =========================
DYNAMIC_MARKET_SCANNER_ENABLED = os.getenv("DYNAMIC_MARKET_SCANNER_ENABLED", "true").lower() == "true"
DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS = int(os.getenv("DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS", "12"))
DYNAMIC_MARKET_SCANNER_REFRESH_SECONDS = int(os.getenv("DYNAMIC_MARKET_SCANNER_REFRESH_SECONDS", str(60 * 60 * 4)))
DYNAMIC_MARKET_SCANNER_FILE = os.path.join("backend", "state", "dynamic_market_scanner.json")
DYNAMIC_MARKET_MIN_PRICE = float(os.getenv("DYNAMIC_MARKET_MIN_PRICE", "3"))
DYNAMIC_MARKET_MAX_PRICE = float(os.getenv("DYNAMIC_MARKET_MAX_PRICE", "800"))
DYNAMIC_MARKET_MIN_VOLUME = int(os.getenv("DYNAMIC_MARKET_MIN_VOLUME", "500000"))
DYNAMIC_MARKET_MAX_SPREAD = float(os.getenv("DYNAMIC_MARKET_MAX_SPREAD", "0.025"))
DYNAMIC_MARKET_YAHOO_SCREENS = [
    s.strip() for s in os.getenv("DYNAMIC_MARKET_YAHOO_SCREENS", "day_gainers,most_actives,aggressive_small_caps").split(",") if s.strip()
]

DYNAMIC_SCANNER_CACHE: Dict[str, Any] = {"updatedAt": "", "symbols": [], "rows": [], "source": "empty", "error": ""}


def _load_dynamic_scanner_cache() -> Dict[str, Any]:
    global DYNAMIC_SCANNER_CACHE
    try:
        if os.path.exists(DYNAMIC_MARKET_SCANNER_FILE):
            with open(DYNAMIC_MARKET_SCANNER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                DYNAMIC_SCANNER_CACHE = {**DYNAMIC_SCANNER_CACHE, **data}
    except Exception as e:
        print(f"DYNAMIC SCANNER LOAD ERROR: {e}")
    return DYNAMIC_SCANNER_CACHE


def _save_dynamic_scanner_cache(data: Dict[str, Any]) -> Dict[str, Any]:
    global DYNAMIC_SCANNER_CACHE
    try:
        os.makedirs(os.path.dirname(DYNAMIC_MARKET_SCANNER_FILE), exist_ok=True)
        with open(DYNAMIC_MARKET_SCANNER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"DYNAMIC SCANNER SAVE ERROR: {e}")
    DYNAMIC_SCANNER_CACHE = {**DYNAMIC_SCANNER_CACHE, **data}
    return DYNAMIC_SCANNER_CACHE


def _dynamic_cache_age_seconds() -> float:
    data = _load_dynamic_scanner_cache()
    try:
        updated = datetime.fromisoformat(str(data.get("updatedAt", "")).replace("Z", "+00:00"))
        return max(0.0, (datetime.now(UTC) - updated).total_seconds())
    except Exception:
        return 999999999.0


def _clean_dynamic_symbol(symbol: str) -> str:
    sym = str(symbol or "").upper().strip()
    # Keep normal US tickers and class shares such as BRK-B, but reject odd Yahoo suffixes.
    if not re.fullmatch(r"[A-Z]{1,5}([.-][A-Z])?", sym):
        return ""
    return sym.replace(".", "-")


def _yahoo_dynamic_screen(screen_id: str, count: int = 50) -> List[Dict[str, Any]]:
    url = f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={screen_id}&count={count}"
    headers = {"User-Agent": "Mozilla/5.0 TradeBot dynamic scanner"}
    response = requests.get(url, headers=headers, timeout=8)
    response.raise_for_status()
    data = response.json()
    quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
    return quotes if isinstance(quotes, list) else []


def _score_dynamic_quote(q: Dict[str, Any], source: str) -> Optional[Dict[str, Any]]:
    symbol = _clean_dynamic_symbol(q.get("symbol"))
    if not symbol or symbol in BLOCKED_WEAK_TICKERS:
        return None

    exchange = str(q.get("fullExchangeName") or q.get("exchange") or "").upper()
    quote_type = str(q.get("quoteType") or "").upper()
    if quote_type and quote_type not in {"EQUITY", "ETF"}:
        return None
    if any(bad in exchange for bad in ["PNK", "OTC", "OTHER OTC"]):
        return None

    price = float(q.get("regularMarketPrice") or q.get("postMarketPrice") or q.get("preMarketPrice") or 0.0)
    volume = int(float(q.get("regularMarketVolume") or q.get("averageDailyVolume3Month") or 0))
    change_pct = float(q.get("regularMarketChangePercent") or 0.0)
    market_cap = float(q.get("marketCap") or 0.0)

    if price < DYNAMIC_MARKET_MIN_PRICE or price > DYNAMIC_MARKET_MAX_PRICE:
        return None
    if volume < DYNAMIC_MARKET_MIN_VOLUME:
        return None

    # Optional live quote spread check using Alpaca. If unavailable, do not reject; just score lower.
    spread = 0.0
    spread_ok = True
    try:
        aq = get_quote(symbol)
        spread = float(aq.get("spread") or 0.0)
        if spread > DYNAMIC_MARKET_MAX_SPREAD:
            spread_ok = False
    except Exception:
        spread = 0.0

    if not spread_ok:
        return None

    score = 0.0
    score += max(-8.0, min(12.0, change_pct)) * 1.25
    score += min(10.0, math.log10(max(volume, 1)) * 1.15)
    if market_cap > 1_000_000_000:
        score += 4.0
    if source == "day_gainers" and change_pct > 0:
        score += 3.0
    if source == "most_actives":
        score += 1.5
    if spread > 0:
        score += max(0.0, 3.0 - (spread * 120.0))

    return {
        "symbol": symbol,
        "score": round(score, 4),
        "reason": f"dynamic scanner | {source} | change={change_pct:.2f}% | volume={volume:,}" + (f" | spread={spread:.4f}" if spread else ""),
        "status": "active",
        "dynamicPick": True,
        "source": source,
        "price": price,
        "changePct": change_pct,
        "volume": volume,
        "marketCap": market_cap,
        "spread": spread,
    }


def refresh_dynamic_market_candidates(force: bool = False) -> Dict[str, Any]:
    if not DYNAMIC_MARKET_SCANNER_ENABLED:
        data = {"enabled": False, "symbols": [], "rows": [], "source": "disabled", "updatedAt": datetime.now(UTC).isoformat(), "error": ""}
        return _save_dynamic_scanner_cache(data)

    if not force and _dynamic_cache_age_seconds() < DYNAMIC_MARKET_SCANNER_REFRESH_SECONDS:
        return _load_dynamic_scanner_cache()

    rows_by_symbol: Dict[str, Dict[str, Any]] = {}
    errors = []

    for screen in DYNAMIC_MARKET_YAHOO_SCREENS:
        try:
            for quote in _yahoo_dynamic_screen(screen, count=60):
                row = _score_dynamic_quote(quote, screen)
                if not row:
                    continue
                prev = rows_by_symbol.get(row["symbol"])
                if not prev or float(row.get("score") or 0) > float(prev.get("score") or 0):
                    rows_by_symbol[row["symbol"]] = row
        except Exception as e:
            errors.append(f"{screen}: {e}")
            print(f"DYNAMIC SCANNER SOURCE ERROR {screen}: {e}")

    rows = sorted(rows_by_symbol.values(), key=lambda r: float(r.get("score") or 0), reverse=True)[:DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS]

    # Safe fallback keeps the bot tradable if external screener data is unavailable.
    if not rows:
        for i, sym in enumerate(QUALITY_ONLY_UNIVERSE[:DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS]):
            rows.append({
                "symbol": sym,
                "score": round(50 - i, 4),
                "reason": "dynamic scanner fallback | core quality universe",
                "status": "active",
                "dynamicPick": False,
                "source": "fallback",
            })

    payload = {
        "enabled": True,
        "mode": "dynamic-market-scanner",
        "updatedAt": datetime.now(UTC).isoformat(),
        "refreshSeconds": DYNAMIC_MARKET_SCANNER_REFRESH_SECONDS,
        "maxSymbols": DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS,
        "source": ",".join(DYNAMIC_MARKET_YAHOO_SCREENS),
        "symbols": [r["symbol"] for r in rows],
        "rows": rows,
        "filters": {
            "minPrice": DYNAMIC_MARKET_MIN_PRICE,
            "maxPrice": DYNAMIC_MARKET_MAX_PRICE,
            "minVolume": DYNAMIC_MARKET_MIN_VOLUME,
            "maxSpread": DYNAMIC_MARKET_MAX_SPREAD,
        },
        "error": " | ".join(errors[-3:]),
    }
    return _save_dynamic_scanner_cache(payload)


def refresh_dynamic_market_candidates_if_needed() -> Dict[str, Any]:
    return refresh_dynamic_market_candidates(force=False)


def dynamic_market_scanner_payload() -> Dict[str, Any]:
    data = _load_dynamic_scanner_cache()
    if not data.get("rows"):
        data = refresh_dynamic_market_candidates(force=False)
    return {"enabled": DYNAMIC_MARKET_SCANNER_ENABLED, **data}


def dynamic_market_rows() -> List[Dict[str, Any]]:
    if not DYNAMIC_MARKET_SCANNER_ENABLED:
        return []
    return list(dynamic_market_scanner_payload().get("rows") or [])


def dynamic_market_symbols() -> List[str]:
    return [str(r.get("symbol", "")).upper() for r in dynamic_market_rows() if r.get("symbol")]


@app.get("/dynamic-market-scanner")
def api_dynamic_market_scanner():
    payload = dynamic_market_scanner_payload()
    return {"ok": True, "dynamicMarketScanner": payload, **payload}


@app.post("/dynamic-market-scanner/refresh")
def api_dynamic_market_scanner_refresh(request: Request):
    verify_api_key(request)
    payload = refresh_dynamic_market_candidates(force=True)
    try:
        apply_quality_only_universe()
        update_status(BOT_NAME, latest_scans)
        latest_status["dynamicMarketScanner"] = payload
        latest_status["lastAction"] = "Dynamic market scanner refreshed"
        latest_status["lastActionAt"] = datetime.now(UTC).isoformat()
    except Exception as e:
        print(f"DYNAMIC SCANNER STATUS UPDATE ERROR: {e}")
    return {"ok": True, "message": "Dynamic market scanner refreshed", "dynamicMarketScanner": payload, **payload}


# =========================
# QUALITY-ONLY UNIVERSE LOCK v1.3
# =========================

QUALITY_ONLY_MODE = os.getenv("QUALITY_ONLY_MODE", "true").lower() == "true"

QUALITY_ONLY_UNIVERSE = [
    "NVDA", "AMD", "MSFT", "AAPL", "META",
    "AMZN", "GOOGL", "GOOG", "AVGO", "NFLX",
    "TSLA", "PLTR", "UBER", "QQQ", "SMH",
]

BLOCKED_WEAK_TICKERS = {
    "LAC", "LCID", "PLUG", "SOFI", "SNAP", "NUVB",
    "RIVN", "F", "AAL", "GIS", "PYPL"
}

def quality_only_symbols():
    symbols = []

    # Manual pins always get first priority unless explicitly blocked.
    try:
        if "load_manual_universe_picks" in globals() and callable(globals()["load_manual_universe_picks"]):
            for sym in load_manual_universe_picks():
                sym = str(sym).upper().strip()
                if sym and sym not in symbols and sym not in BLOCKED_WEAK_TICKERS:
                    symbols.append(sym)
    except Exception as e:
        print(f"QUALITY ONLY MANUAL MERGE ERROR: {e}")

    # Dynamic scanner picks are the main discovery layer.
    try:
        if DYNAMIC_MARKET_SCANNER_ENABLED:
            for sym in dynamic_market_symbols():
                sym = str(sym).upper().strip()
                if sym and sym not in symbols and sym not in BLOCKED_WEAK_TICKERS:
                    symbols.append(sym)
    except Exception as e:
        print(f"QUALITY ONLY DYNAMIC MERGE ERROR: {e}")

    # Core quality names are the safety fallback and stable baseline.
    for sym in QUALITY_ONLY_UNIVERSE:
        sym = str(sym).upper().strip()
        if sym and sym not in symbols and sym not in BLOCKED_WEAK_TICKERS:
            symbols.append(sym)

    return symbols

def quality_only_rows():
    rows = []
    dynamic_by_symbol = {}
    try:
        dynamic_by_symbol = {str(r.get("symbol", "")).upper(): r for r in dynamic_market_rows()}
    except Exception:
        dynamic_by_symbol = {}

    manual_picks = set()
    try:
        manual_picks = {str(s).upper() for s in load_manual_universe_picks()}
    except Exception:
        manual_picks = set()

    for i, sym in enumerate(quality_only_symbols()):
        dyn = dynamic_by_symbol.get(sym)
        is_manual = sym in manual_picks
        is_dynamic = bool(dyn)
        base_score = 100 - (i * 3.0)
        score = float(dyn.get("score", base_score)) if dyn else base_score
        reason = dyn.get("reason") if dyn else "core quality universe | weak tickers blocked"
        if is_manual:
            reason = "manual pick | pinned to universe" + (f" | {reason}" if reason else "")
            score = max(score, 99.0)
        rows.append({
            "symbol": sym,
            "score": round(score, 2),
            "reason": reason,
            "status": "active",
            "manualPick": is_manual,
            "dynamicPick": is_dynamic,
            "source": dyn.get("source") if dyn else "core-quality",
            "changePct": dyn.get("changePct") if dyn else None,
            "volume": dyn.get("volume") if dyn else None,
            "price": dyn.get("price") if dyn else None,
        })
    return rows

def apply_quality_only_universe():
    global current_universe, SAFE_UNIVERSE, UNIVERSE, AUTO_UNIVERSE_CANDIDATE_POOL

    symbols = quality_only_symbols()
    rows = quality_only_rows()

    try:
        current_universe = symbols[:]
    except Exception:
        pass

    try:
        SAFE_UNIVERSE = symbols[:]
    except Exception:
        pass

    try:
        UNIVERSE = symbols[:]
    except Exception:
        pass

    try:
        AUTO_UNIVERSE_CANDIDATE_POOL = symbols[:]
    except Exception:
        pass

    try:
        latest_status["autoUniverse"] = {
            "enabled": True,
            "mode": "dynamic-quality-hybrid" if DYNAMIC_MARKET_SCANNER_ENABLED else "quality-only",
            "size": len(symbols),
            "activeSymbols": symbols,
            "rows": rows,
            "blockedWeakTickers": sorted(list(BLOCKED_WEAK_TICKERS)),
            "dynamicScanner": dynamic_market_scanner_payload() if "dynamic_market_scanner_payload" in globals() else {},
            "lastRefresh": datetime.now(UTC).isoformat(),
            "manualPickCount": len([s for s in symbols if s not in QUALITY_ONLY_UNIVERSE]),
        }
        latest_status["lastAction"] = "Quality-only universe applied"
        latest_status["lastActionAt"] = datetime.now(UTC).isoformat()
    except Exception as e:
        print(f"QUALITY ONLY STATUS ERROR: {e}")

    return symbols

def is_quality_blocked_symbol(symbol: str) -> bool:
    sym = str(symbol).upper().strip()
    if not QUALITY_ONLY_MODE:
        return False
    if sym in BLOCKED_WEAK_TICKERS:
        return True
    if sym not in quality_only_symbols():
        return True
    return False

def quality_buy_check(symbol: str):
    sym = str(symbol).upper().strip()
    if is_quality_blocked_symbol(sym):
        return {
            "ok": False,
            "reason": f"{sym} blocked by quality-only universe",
        }
    return {"ok": True, "reason": "quality approved"}

# Apply immediately on startup/redeploy.
try:
    apply_quality_only_universe()
except Exception as e:
    print(f"QUALITY ONLY STARTUP APPLY ERROR: {e}")

@app.get("/quality-universe")
def api_quality_universe():
    return {
        "ok": True,
        "qualityOnlyMode": QUALITY_ONLY_MODE,
        "activeSymbols": quality_only_symbols(),
        "blockedWeakTickers": sorted(list(BLOCKED_WEAK_TICKERS)),
        "rows": quality_only_rows(),
    }

@app.post("/apply-quality-universe")
def api_apply_quality_universe(request: Request):
    verify_api_key(request)
    symbols = apply_quality_only_universe()
    try:
        update_status(BOT_NAME, latest_scans)
        apply_quality_only_universe()
    except Exception as e:
        print(f"APPLY QUALITY UPDATE_STATUS ERROR: {e}")
    return {
        "ok": True,
        "message": "Quality-only universe applied",
        "activeSymbols": symbols,
        "blockedWeakTickers": sorted(list(BLOCKED_WEAK_TICKERS)),
    }




# =========================
# FORCE QUALITY UNIVERSE STATUS/UI PATCH
# =========================

def force_quality_auto_universe_payload():
    try:
        if "quality_only_rows" in globals():
            rows = quality_only_rows()
        elif "quality_universe_rows" in globals():
            rows = quality_universe_rows()
        else:
            rows = []
        symbols = [r["symbol"] for r in rows]
    except Exception:
        rows = []
        symbols = []

    if not symbols:
        symbols = [
            "NVDA", "AMD", "MSFT", "AAPL", "META",
            "AMZN", "GOOGL", "GOOG", "AVGO", "NFLX",
            "TSLA", "PLTR", "UBER", "QQQ", "SMH",
        ]
        rows = [
            {
                "symbol": s,
                "score": round(100 - (i * 3), 2),
                "reason": "quality-only universe | forced UI sync",
                "status": "active",
            }
            for i, s in enumerate(symbols)
        ]

    return {
        "enabled": True,
        "mode": "dynamic-quality-hybrid" if DYNAMIC_MARKET_SCANNER_ENABLED else "quality-only",
        "size": len(symbols),
        "weekStart": datetime.now(UTC).date().isoformat(),
        "monthStart": datetime.now(UTC).replace(day=1).date().isoformat(),
        "activeSymbols": symbols,
        "rows": rows,
        "lastRefresh": datetime.now(UTC).isoformat(),
        "candidatePoolSize": len(symbols),
        "dynamicPickCount": len([r for r in rows if r.get("dynamicPick")]),
        "manualPickCount": len([r for r in rows if r.get("manualPick")]),
        "dynamicScanner": dynamic_market_scanner_payload() if "dynamic_market_scanner_payload" in globals() else {},
        "keepWinners": True,
    }

@app.get("/weekly-universe")
def weekly_universe():
    payload = force_quality_auto_universe_payload()
    try:
        latest_status["autoUniverse"] = payload
    except Exception:
        pass
    return {"ok": True, "autoUniverse": payload, **payload}

@app.post("/refresh-universe")
def refresh_universe(request: Request):
    """
    Fast weekly stock refresh route for the dashboard button.

    Important fix:
    - Do not wait behind the trading bot lock.
    - Do not run slow scans/trading work here.
    - Update current_universe + latest_status immediately so /status and /weekly-universe
      show the refreshed list straight away.
    """
    print("BUTTON HIT: refresh-universe", flush=True)
    verify_api_key(request)

    try:
        if "refresh_dynamic_market_candidates" in globals():
            refresh_dynamic_market_candidates(force=True)
        if "apply_quality_only_universe" in globals():
            apply_quality_only_universe()
        elif "apply_quality_universe_to_status" in globals():
            apply_quality_universe_to_status()
    except Exception as e:
        print(f"QUALITY APPLY ERROR: {e}")

    payload = force_quality_auto_universe_payload()
    symbols = list(dict.fromkeys([str(s).upper().strip() for s in payload.get("activeSymbols", []) if str(s).strip()]))

    try:
        global current_universe, last_universe_refresh_ts
        if symbols:
            current_universe = symbols
            for sym in current_universe:
                ensure_symbol_state(sym, custom=sym in custom_symbols)
        last_universe_refresh_ts = time.time()
    except Exception as e:
        print(f"REFRESH UNIVERSE STATE ERROR: {e}")

    try:
        latest_status["autoUniverse"] = payload
        latest_status["universe"] = symbols or payload.get("activeSymbols", [])
        latest_status["lastAction"] = "Quality-only weekly universe refreshed"
        latest_status["lastActionAt"] = datetime.now(UTC).isoformat()
        latest_status["autoUniverseEnabled"] = True
        latest_status["dynamicMarketScanner"] = dynamic_market_scanner_payload() if "dynamic_market_scanner_payload" in globals() else {}
    except Exception as e:
        print(f"REFRESH UNIVERSE STATUS ERROR: {e}")

    return {
        "ok": True,
        "message": "Dynamic market universe refreshed",
        "autoUniverse": payload,
        "activeSymbols": symbols or payload.get("activeSymbols", []),
        "rows": payload.get("rows", []),
    }

@app.get("/refresh-universe-preview")
def refresh_universe_preview():
    print("BUTTON HIT: refresh-universe", flush=True)
    payload = force_quality_auto_universe_payload()
    return {
        "ok": True,
        "message": "Preview of quality-only universe",
        "activeSymbols": payload["activeSymbols"],
        "rows": payload["rows"],
        "autoUniverse": payload,
    }




# ============================================================
# PROFIT BANKING / PERSISTENT TRADING CAP OVERRIDE
# ============================================================

def trading_cap_file_path() -> str:
    """Persistent cap file.

    On Render, set TRADING_CAP_FILE to your disk path if your disk is not mounted
    at /var/data. If /var/data exists, the bot will use it automatically.
    """
    env_path = os.getenv("TRADING_CAP_FILE", "").strip()
    if env_path:
        return env_path
    if os.path.isdir("/var/data"):
        return "/var/data/trading_cap.json"
    base = os.getenv("RENDER_DISK_PATH", "backend/state")
    return os.path.join(base, "trading_cap.json")


def _default_trading_cap_usd() -> float:
    try:
        return float(os.getenv("MAX_TRADING_CAPITAL", str(MAX_TRADING_CAPITAL or 200)) or 200)
    except Exception:
        return 200.0


def load_trading_cap_setting() -> Dict[str, Any]:
    path = trading_cap_file_path()
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            value = float(data.get("value") or 0)
            currency = str(data.get("currency") or "GBP").upper()
            if value > 0 and currency in ["GBP", "USD"]:
                return {
                    "value": value,
                    "currency": currency,
                    "source": "saved",
                    "path": path,
                    "updatedAt": data.get("updatedAt", ""),
                }
    except Exception as e:
        print(f"TRADING CAP LOAD ERROR: {e}")

    # Backwards-compatible fallback: old env/code cap is USD.
    return {
        "value": _default_trading_cap_usd(),
        "currency": "USD",
        "source": "env",
        "path": path,
        "updatedAt": "",
    }


def save_trading_cap_setting(value: float, currency: str = "GBP") -> Dict[str, Any]:
    currency = str(currency or "GBP").upper().strip()
    if currency not in ["GBP", "USD"]:
        currency = "GBP"
    value = float(value or 0)
    if value < 0:
        value = 0.0

    path = trading_cap_file_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "value": round(value, 2),
        "currency": currency,
        "updatedAt": datetime.now(UTC).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return load_trading_cap_setting()


def trading_cap_usd() -> float:
    setting = load_trading_cap_setting()
    value = float(setting.get("value") or 0.0)
    currency = str(setting.get("currency") or "USD").upper()
    if value <= 0:
        return 0.0
    if currency == "GBP":
        rate = get_usd_to_gbp_rate() or FX_FALLBACK_USD_TO_GBP
        return value / max(rate, 0.0001)
    return value


def trading_cap_gbp() -> float:
    setting = load_trading_cap_setting()
    value = float(setting.get("value") or 0.0)
    currency = str(setting.get("currency") or "USD").upper()
    if value <= 0:
        return 0.0
    if currency == "GBP":
        return value
    return money_gbp(value)


def effective_trading_equity(account_equity: float) -> float:
    try:
        equity = float(account_equity or 0)
    except Exception:
        equity = 0.0

    cap = trading_cap_usd()
    return max(0.0, min(equity, cap)) if cap > 0 else max(0.0, equity)


def banking_payload():
    try:
        account = get_account()
        equity = float(account.equity)
    except Exception:
        equity = 0.0

    setting = load_trading_cap_setting()
    cap_usd = trading_cap_usd()
    cap_gbp = trading_cap_gbp()

    effective = max(0.0, min(equity, cap_usd)) if cap_usd > 0 else max(0.0, equity)
    banked = max(0.0, equity - effective) if cap_usd > 0 else 0.0

    return {
        "ok": True,
        "enabled": cap_usd > 0,
        "maxTradingCapital": cap_usd,
        "maxTradingCapitalUsd": cap_usd,
        "maxTradingCapitalGbp": cap_gbp,
        "tradingCapValue": float(setting.get("value") or 0.0),
        "tradingCapCurrency": setting.get("currency", "USD"),
        "tradingCapSource": setting.get("source", "env"),
        "tradingCapFile": setting.get("path", trading_cap_file_path()),
        "tradingCapUpdatedAt": setting.get("updatedAt", ""),
        "accountEquity": equity,
        "effectiveTradingEquity": effective,
        "effectiveTradingEquityGbp": money_gbp(effective),
        "bankedProfitCashBuffer": banked,
        "bankedProfitCashBufferGbp": money_gbp(banked),
        "message": "Profit banking active" if cap_usd > 0 else "Profit banking disabled",
    }


@app.get("/banking-status")
def api_banking_status():
    return {"ok": True, **banking_payload()}


@app.get("/trading-cap")
def api_get_trading_cap():
    return {"ok": True, **banking_payload()}


@app.post("/trading-cap")
def api_set_trading_cap(request: Request, payload: dict = Body(...)):
    verify_api_key(request)
    try:
        # Dashboard sends GBP by default, because that is how the user thinks
        # about the trading cap. Backend converts it to USD internally for Alpaca.
        value = payload.get("capGbp", payload.get("value", payload.get("cap")))
        currency = str(payload.get("currency", "GBP")).upper()
        value = float(value)
        if value <= 0:
            return {"ok": False, "message": "Trading cap must be greater than 0"}
        setting = save_trading_cap_setting(value, currency)
        payload_out = banking_payload()
        try:
            latest_status["banking"] = payload_out
            latest_status["newPositionNotional"] = calculate_new_position_notional()
            latest_status["lastAction"] = f"Trading cap saved: {currency} {value:.2f}"
            latest_status["lastActionAt"] = datetime.now(UTC).isoformat()
        except Exception:
            pass
        return {
            "ok": True,
            "message": f"Trading cap saved at {currency} {value:.2f}",
            "setting": setting,
            **payload_out,
        }
    except Exception as e:
        return {"ok": False, "message": f"Could not save trading cap: {e}"}



# =========================
# BACKTEST / PAPER REPLAY REPORT
# =========================
@app.post("/backtest-replay")
def api_backtest_replay(payload: dict = Body(default={}), request: Request = None):
    if request is not None:
        verify_api_key(request)

    try:
        cap_gbp = float(payload.get("capGbp") or 0.0)
    except Exception:
        cap_gbp = 0.0

    try:
        rate = get_usd_to_gbp_rate()
    except Exception:
        rate = FX_FALLBACK_USD_TO_GBP

    cap_usd = cap_gbp / max(rate, 0.0001) if cap_gbp > 0 else 0.0

    try:
        closed = closed_trades_from_db(10000)
    except Exception:
        closed = []

    rows = []
    equity = cap_gbp if cap_gbp > 0 else 0.0
    peak = equity
    max_drawdown = 0.0
    wins = 0
    losses = 0
    total_pnl_gbp = 0.0
    total_pnl_usd = 0.0
    by_symbol: Dict[str, Dict[str, Any]] = {}

    for t in closed:
        try:
            symbol = str(t.get("symbol", "")).upper()
            pnl_usd = float(t.get("pnl") or 0.0)
            pnl_gbp = float(t.get("pnlGbp") or (pnl_usd * rate))
            if not symbol:
                continue

            wins += 1 if pnl_usd >= 0 else 0
            losses += 1 if pnl_usd < 0 else 0
            total_pnl_usd += pnl_usd
            total_pnl_gbp += pnl_gbp
            equity += pnl_gbp
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, peak - equity)

            row = by_symbol.setdefault(symbol, {
                "symbol": symbol,
                "trades": 0,
                "wins": 0,
                "losses": 0,
                "pnlUsd": 0.0,
                "pnlGbp": 0.0,
                "winRate": 0.0,
            })
            row["trades"] += 1
            row["wins"] += 1 if pnl_usd >= 0 else 0
            row["losses"] += 1 if pnl_usd < 0 else 0
            row["pnlUsd"] += pnl_usd
            row["pnlGbp"] += pnl_gbp

            rows.append({
                "time": t.get("time") or t.get("timestamp") or "",
                "symbol": symbol,
                "pnlUsd": pnl_usd,
                "pnlGbp": pnl_gbp,
                "equityGbp": equity,
            })
        except Exception:
            continue

    symbol_rows = []
    for row in by_symbol.values():
        row["winRate"] = row["wins"] / max(1, row["trades"])
        row["pnlUsd"] = round(float(row["pnlUsd"]), 4)
        row["pnlGbp"] = round(float(row["pnlGbp"]), 4)
        symbol_rows.append(row)

    symbol_rows.sort(key=lambda r: float(r.get("pnlGbp") or 0.0), reverse=True)
    best_symbol = symbol_rows[0]["symbol"] if symbol_rows else "—"
    worst_symbol = symbol_rows[-1]["symbol"] if symbol_rows else "—"

    return {
        "ok": True,
        "message": "Backtest / paper replay report complete",
        "capGbp": cap_gbp,
        "capUsd": cap_usd,
        "tradesTested": len(rows),
        "wins": wins,
        "losses": losses,
        "winRate": wins / max(1, wins + losses),
        "replayPnlUsd": round(total_pnl_usd, 4),
        "replayPnlGbp": round(total_pnl_gbp, 4),
        "endingEquityGbp": round(equity, 4),
        "maxDrawdownGbp": round(max_drawdown, 4),
        "bestSymbol": best_symbol,
        "worstSymbol": worst_symbol,
        "bySymbol": symbol_rows,
        "equityCurve": rows[-500:],
        "notes": "Uses matched closed-trade history. It is a reporting replay, not a live trade signal and does not place orders.",
    }
