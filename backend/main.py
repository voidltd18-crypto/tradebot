import os
import json
import time
import secrets
MAX_TRADING_CAPITAL = float(os.getenv("MAX_TRADING_CAPITAL", "200") or 200)

import sqlite3
import math
import re
import threading
import random
from datetime import datetime, UTC, timedelta
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional

import requests
from fastapi import FastAPI, Request, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, StockBarsRequest
from alpaca.data.timeframe import TimeFrame


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

# Guarded adaptive optimiser. Disabled by default; advisory/stability tracking still runs.
V2_AUTO_APPLY_THRESHOLDS = os.getenv("V2_AUTO_APPLY_THRESHOLDS", "false").lower() == "true"
V2_OPTIMIZER_REQUIRED_STABLE_RUNS = int(os.getenv("V2_OPTIMIZER_REQUIRED_STABLE_RUNS", "5") or 5)
V2_OPTIMIZER_MIN_IMPROVEMENT = float(os.getenv("V2_OPTIMIZER_MIN_IMPROVEMENT", "0.08") or 0.08)
V2_OPTIMIZER_MAX_DRAWDOWN_INCREASE = float(os.getenv("V2_OPTIMIZER_MAX_DRAWDOWN_INCREASE", "0.10") or 0.10)
V2_OPTIMIZER_MAX_CONF_STEP = float(os.getenv("V2_OPTIMIZER_MAX_CONF_STEP", "0.04") or 0.04)
V2_OPTIMIZER_MAX_QUALITY_STEP = float(os.getenv("V2_OPTIMIZER_MAX_QUALITY_STEP", "0.004") or 0.004)

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

MAX_POSITIONS = 1
MAX_NEW_BUYS_PER_LOOP = 1
MAX_POSITION_VALUE_PCT = 0.12
TARGET_POSITION_VALUE_PCT = 0.08
MIN_ORDER_NOTIONAL = 1.00
CASH_BUFFER = 0.50

# Full-buy mode:
# When max positions is 1, use nearly all available trading capital/buying power
# instead of small partial sizing.
FULL_BUY_WHEN_ONE_POSITION = os.getenv("FULL_BUY_WHEN_ONE_POSITION", "true").lower() == "true"
FULL_BUY_CASH_BUFFER = float(os.getenv("FULL_BUY_CASH_BUFFER", "2.00") or 2.00)

MAX_SPREAD = 0.015
PREFER_SPREAD_UNDER = 0.006

BUY_DIP = 0.9985
MIN_PULLBACK = 0.0010
MAX_PULLBACK = 0.0450
MIN_TICKS_BEFORE_BUY = 3
MOMENTUM_LOOKBACK_POINTS = 5
MIN_SHORT_MOMENTUM = -0.015
MAX_SHORT_MOMENTUM = 0.045

STOP_LOSS = 0.960
TRAIL_START = 1.060
TRAIL_GIVEBACK = 0.980

MAX_DAILY_LOSS = -100.00
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
HARD_STOP_LOSS_PCT = -4.50
MAX_NEW_BUYS_PER_DAY_PDT_AWARE = 6

# Faster Exit / Partial Profit Mode
FAST_EXIT_MODE_ENABLED = True
PARTIAL_PROFIT_ENABLED = False
PARTIAL_PROFIT_TRIGGER_PCT = 8.00
PARTIAL_PROFIT_SELL_PCT = 0.00
POST_PARTIAL_TRAIL_GIVEBACK = 0.980
FAST_STOP_LOSS_PCT = -4.00
STALL_EXIT_ENABLED = True
STALL_EXIT_AFTER_MINUTES = 4320
STALL_EXIT_MIN_PNL_PCT = -1.00

# Swing Hold AI: learns from closed-trade history and avoids quick exits.
SWING_SNIPER_SAFE_MODE = True
HOLD_AI_ENABLED = True
HOLD_AI_LOOKBACK_DAYS = int(os.getenv("HOLD_AI_LOOKBACK_DAYS", "180") or 180)
HOLD_AI_MIN_TRADES = int(os.getenv("HOLD_AI_MIN_TRADES", "4") or 4)
HOLD_AI_MIN_HOLD_MINUTES = 1440       # default: at least 1 trading day
HOLD_AI_GOOD_SYMBOL_HOLD_MINUTES = 2880
HOLD_AI_WEAK_SYMBOL_HOLD_MINUTES = 720
HOLD_AI_MAX_STALL_MINUTES = 4320      # only consider a stall exit after 3 days
HOLD_AI_MIN_TRAIL_PROFIT_PCT = 6.00
HOLD_AI_TRAIL_GIVEBACK_PCT = 2.00
MIN_SELL_NOTIONAL = 1.00

# =========================
# TRADEBOT V2 SAFETY / EXPECTANCY ENGINE
# =========================
# V2 starts in validation-only mode. It will scan and explain trades, but it
# will not place a new live buy until TRADEBOT_V2_LIVE_ENABLED=true is set.
TRADEBOT_V2_ENABLED = os.getenv("TRADEBOT_V2_ENABLED", "true").lower() == "true"
TRADEBOT_V2_LIVE_ENABLED = os.getenv("TRADEBOT_V2_LIVE_ENABLED", "false").lower() == "true"
V2_MIN_SYMBOL_SAMPLES = int(os.getenv("V2_MIN_SYMBOL_SAMPLES", "8") or 8)
V2_MIN_WIN_RATE = float(os.getenv("V2_MIN_WIN_RATE", "0.50") or 0.50)
V2_MIN_PROFIT_FACTOR = float(os.getenv("V2_MIN_PROFIT_FACTOR", "1.10") or 1.10)
V2_MIN_EXPECTANCY_PCT = float(os.getenv("V2_MIN_EXPECTANCY_PCT", "0.10") or 0.10)
V2_LOOKBACK_DAYS = int(os.getenv("V2_LOOKBACK_DAYS", "365") or 365)
V2_LOG_DECISIONS = os.getenv("V2_LOG_DECISIONS", "true").lower() == "true"
V2_DECISION_DEDUPE_SECONDS = int(os.getenv("V2_DECISION_DEDUPE_SECONDS", "300") or 300)
V2_OUTCOME_HORIZONS_HOURS = tuple(int(x.strip()) for x in os.getenv("V2_OUTCOME_HORIZONS_HOURS", "1,24,72,120").split(",") if x.strip())
V2_OUTCOME_BATCH_SIZE = int(os.getenv("V2_OUTCOME_BATCH_SIZE", "100"))
V2_INDEPENDENT_SAMPLE_MINUTES = int(os.getenv("V2_INDEPENDENT_SAMPLE_MINUTES", "30"))
V2_ESTIMATED_COST_BPS = float(os.getenv("V2_ESTIMATED_COST_BPS", "10"))

# TradeBot V4.1 intelligence foundation. Advisory/data-collection only.
V4_MARKET_DNA_ENABLED = os.getenv("V4_MARKET_DNA_ENABLED", "true").lower() == "true"
V4_SIMILARITY_MIN_SAMPLES = int(os.getenv("V4_SIMILARITY_MIN_SAMPLES", "8") or 8)
V4_SIMILARITY_LIMIT = int(os.getenv("V4_SIMILARITY_LIMIT", "50") or 50)
V4_PATTERN_MIN_SAMPLES = int(os.getenv("V4_PATTERN_MIN_SAMPLES", "8") or 8)

# TradeBot V5.1 Replay Laboratory. Research/advisory only.
V5_REPLAY_ENABLED = os.getenv("V5_REPLAY_ENABLED", "true").lower() == "true"
V5_REPLAY_DEFAULT_HORIZON_HOURS = int(os.getenv("V5_REPLAY_DEFAULT_HORIZON_HOURS", "24") or 24)
V5_REPLAY_MIN_SAMPLES = int(os.getenv("V5_REPLAY_MIN_SAMPLES", "8") or 8)
V5_REPLAY_MAX_ROWS = int(os.getenv("V5_REPLAY_MAX_ROWS", "10000") or 10000)

# TradeBot V6.4 Outcome-Time Forensics. Historical checkpoint evidence only.
V6_BRAINS_ENABLED = os.getenv("V6_BRAINS_ENABLED", "true").lower() == "true"
V6_DEFAULT_HORIZON_HOURS = int(os.getenv("V6_DEFAULT_HORIZON_HOURS", "24") or 24)
V6_MIN_SAMPLES = int(os.getenv("V6_MIN_SAMPLES", "12") or 12)
V6_RECOMMENDATION_MIN_PF = float(os.getenv("V6_RECOMMENDATION_MIN_PF", "1.15") or 1.15)
V6_RECOMMENDATION_MIN_EXPECTANCY = float(os.getenv("V6_RECOMMENDATION_MIN_EXPECTANCY", "0.10") or 0.10)
V6_ACTIVE_BRAIN = os.getenv("V6_ACTIVE_BRAIN", "current_a_plus").strip().lower() or "current_a_plus"
V6_AUTO_SYNC_ENABLED = os.getenv("V6_AUTO_SYNC_ENABLED", "true").lower() == "true"
V6_AUTO_SYNC_INTERVAL_SECONDS = max(30, int(os.getenv("V6_AUTO_SYNC_INTERVAL_SECONDS", "300") or 300))
V6_AUTO_SYNC_LIMIT = max(100, min(int(os.getenv("V6_AUTO_SYNC_LIMIT", "50000") or 50000), 50000))
V6_OUTCOME_MAX_DELAY_MINUTES = max(1, int(os.getenv("V6_OUTCOME_MAX_DELAY_MINUTES", "30") or 30))
V6_HISTORICAL_BAR_LOOKBACK_MINUTES = max(5, int(os.getenv("V6_HISTORICAL_BAR_LOOKBACK_MINUTES", "15") or 15))
V6_HISTORICAL_BAR_LOOKAHEAD_MINUTES = max(5, int(os.getenv("V6_HISTORICAL_BAR_LOOKAHEAD_MINUTES", "45") or 45))
V6_REPAIR_BATCH_SIZE = max(1, min(int(os.getenv("V6_REPAIR_BATCH_SIZE", "200") or 200), 1000))

# TradeBot V7.1 Autonomous Research Lab. Shadow-only; never changes live trading.
V7_ENABLED = os.getenv("V7_ENABLED", "true").lower() == "true"
V7_AUTOMATIC_EVOLUTION = os.getenv("V7_AUTOMATIC_EVOLUTION", "true").lower() == "true"
V7_POPULATION_LIMIT = max(6, min(int(os.getenv("V7_POPULATION_LIMIT", "30") or 30), 200))
V7_CHILDREN_PER_RUN = max(1, min(int(os.getenv("V7_CHILDREN_PER_RUN", "12") or 12), 50))
V7_MIN_PARENT_SAMPLES = max(V6_MIN_SAMPLES, int(os.getenv("V7_MIN_PARENT_SAMPLES", "20") or 20))
V7_MUTATION_RATE = max(0.01, min(float(os.getenv("V7_MUTATION_RATE", "0.12") or 0.12), 0.50))
V7_WEEKEND_MAINTENANCE_ENABLED = os.getenv("V7_WEEKEND_MAINTENANCE_ENABLED", "true").lower() == "true"
V7_WEEKEND_DAY = max(0, min(int(os.getenv("V7_WEEKEND_DAY", "6") or 6), 6))  # Monday=0, Sunday=6
V7_WEEKEND_HOUR_UK = max(0, min(int(os.getenv("V7_WEEKEND_HOUR_UK", "6") or 6), 23))

# V2 deliberately disables rotation/churn. Existing positions are still
# protected by hard-stop and swing-management rules.
if TRADEBOT_V2_ENABLED:
    ROTATION_MODE_ENABLED = False
    MAX_NEW_BUYS_PER_LOOP = 1
    MAX_POSITIONS = 1

# Profit Optimiser / Analytics / Auto-Improve
PROFIT_OPTIMIZER_ENABLED = True
ANALYTICS_ENABLED = True
AUTO_IMPROVE_ENABLED = True

DAILY_PROFIT_TARGET = 4.00
DAILY_LOSS_LIMIT_OPTIMIZER = -100.00
PAUSE_BUYS_AFTER_DAILY_TARGET = True
PAUSE_BUYS_AFTER_DAILY_LOSS = True

OPTIMIZED_STOP_LOSS = 0.960
OPTIMIZED_TRAIL_START = 1.060
OPTIMIZED_TRAIL_GIVEBACK = 0.980
OPTIMIZED_FAST_STOP_LOSS_PCT = -4.00
OPTIMIZED_PARTIAL_PROFIT_TRIGGER_PCT = 8.00
OPTIMIZED_PARTIAL_PROFIT_SELL_PCT = 0.00

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
A_PLUS_MIN_QUALITY = 0.03
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
v6_sync_thread_started = False
v7_weekend_thread_started = False
v6_last_sync_result: Dict[str, Any] = {}
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

    # Full-buy mode for one-position trading.
    # Uses nearly all available capped trading capital/buying power, leaving a small buffer.
    if FULL_BUY_WHEN_ONE_POSITION and int(MAX_POSITIONS) <= 1:
        usable_cash = max(0.0, buying_power - FULL_BUY_CASH_BUFFER)
        return round(max(0.0, min(sizing_equity, usable_cash)), 2)

    target_value = sizing_equity * TARGET_POSITION_VALUE_PCT
    max_value = sizing_equity * MAX_POSITION_VALUE_PCT
    usable_cash = max(0.0, buying_power - CASH_BUFFER)
    return round(max(0.0, min(target_value, max_value, usable_cash)), 2)


def confidence_notional(scan):
    base = calculate_new_position_notional()

    # In one-position full-buy mode, do not downsize by confidence.
    # The entry gates still control trade quality; this only changes allocation size.
    if FULL_BUY_WHEN_ONE_POSITION and int(MAX_POSITIONS) <= 1:
        return base

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


def proposed_buy_qty(scan: Dict[str, Any]) -> float:
    """Display-only estimate. Live orders still use notional sizing at submission time."""
    try:
        price = float(scan.get("price") or 0.0)
        if price <= 0:
            return 0.0
        notional = float(confidence_notional(scan))
        return floor_qty(notional / price, 6)
    except Exception:
        return 0.0


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
# SWING HOLD AI HELPERS
# =========================
def _parse_trade_dt(value: Any):
    try:
        if not value:
            return None
        txt = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(txt)
    except Exception:
        return None


def hold_ai_symbol_profile(symbol: str):
    """Small, safe learning layer from rebuilt closed trades.
    It does not predict prices. It only decides whether this symbol deserves
    more patience or should be treated cautiously based on its own history.
    """
    sym = str(symbol or "").upper()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    cutoff = datetime.now(UTC) - timedelta(days=HOLD_AI_LOOKBACK_DAYS)
    trades = []
    for t in closed:
        if str(t.get("symbol", "")).upper() != sym:
            continue
        dt = _parse_trade_dt(t.get("timestamp"))
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt is not None and dt < cutoff:
            continue
        trades.append(t)

    wins = [t for t in trades if float(t.get("pnl") or 0.0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0.0) < 0]
    total = sum(float(t.get("pnl") or 0.0) for t in trades)
    avg_pct = sum(float(t.get("pnlPct") or 0.0) for t in trades) / max(1, len(trades))
    win_rate = len(wins) / max(1, len(trades))

    if len(trades) >= HOLD_AI_MIN_TRADES and win_rate >= 0.55 and total > 0:
        bias = "PATIENT"
        min_hold = HOLD_AI_GOOD_SYMBOL_HOLD_MINUTES
    elif len(trades) >= HOLD_AI_MIN_TRADES and (win_rate <= 0.40 or total < 0):
        bias = "CAUTIOUS"
        min_hold = HOLD_AI_WEAK_SYMBOL_HOLD_MINUTES
    else:
        bias = "NORMAL"
        min_hold = HOLD_AI_MIN_HOLD_MINUTES

    return {
        "symbol": sym,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": win_rate,
        "totalPnl": total,
        "avgPnlPct": avg_pct,
        "bias": bias,
        "minHoldMinutes": int(min_hold),
    }


def hold_ai_min_hold_minutes(symbol: str):
    if not HOLD_AI_ENABLED:
        return 0
    return int(hold_ai_symbol_profile(symbol).get("minHoldMinutes") or HOLD_AI_MIN_HOLD_MINUTES)


def hold_ai_blocks_soft_exit(position: Dict[str, Any], exit_reason: str):
    """Returns True when Swing AI should keep holding instead of taking a soft exit.
    Hard stops are intentionally not blocked.
    """
    if not HOLD_AI_ENABLED:
        return False, "hold ai off"

    symbol = str(position.get("symbol", "")).upper()
    pnl_pct = float(position.get("pnlPct") or 0.0)
    minutes = int(position.get("minutesSinceBuy") or 999999)
    min_hold = hold_ai_min_hold_minutes(symbol)
    profile = hold_ai_symbol_profile(symbol)

    # Never soft-sell the same day unless it is a hard stop. This protects the
    # account from PDT churn and stops the bot from scalping tiny moves.
    if was_bought_today(symbol):
        return True, f"HOLD AI same-day hold for {symbol}; soft exit blocked ({exit_reason})"

    # Give valid swing setups time to develop unless they are near the hard stop.
    if minutes < min_hold and pnl_pct > FAST_STOP_LOSS_PCT:
        return True, f"HOLD AI {profile['bias']} min hold {minutes}/{min_hold}m; pnl={pnl_pct:.2f}%"

    return False, f"HOLD AI allows {exit_reason}; {profile['bias']}"


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
    if HOLD_AI_ENABLED:
        return False, "swing hold ai: partial profit disabled"
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

    ai_min = hold_ai_min_hold_minutes(symbol) if HOLD_AI_ENABLED else STALL_EXIT_AFTER_MINUTES
    effective_stall = max(STALL_EXIT_AFTER_MINUTES, ai_min)

    if minutes < effective_stall:
        return False, f"held {minutes}m below swing stall timer {effective_stall}m"

    if HOLD_AI_ENABLED and pnl_pct > -1.00:
        return False, f"hold ai: pnl {pnl_pct:.2f}% not weak enough for stall exit"

    if pnl_pct > STALL_EXIT_MIN_PNL_PCT:
        return False, f"pnl {pnl_pct:.2f}% above stall minimum"

    if was_bought_today(symbol) and PDT_AWARE_MODE_ENABLED:
        return False, "PDT-aware hold; stall exit skipped today"

    return True, f"stall exit: held {minutes}m pnl={pnl_pct:.2f}%"



# =========================
# TRADEBOT V2 EXPECTANCY HELPERS
# =========================
def v2_forward_shadow_profile(symbol: str, preferred_horizon: int = 24) -> Dict[str, Any]:
    """Forward replay evidence only. This never changes the live gate."""
    sym = str(symbol or "").upper().strip()
    if not (SQLITE_ENABLED and sym):
        return {"symbol": sym, "mode": "SHADOW", "recommendation": "WATCH", "samples": 0}
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            """WITH ranked AS (
                   SELECT o.*,
                          ROW_NUMBER() OVER (
                              PARTITION BY COALESCE(o.sample_key, CAST(o.decision_id AS TEXT)), o.horizon_hours
                              ORDER BY o.id ASC
                          ) AS rn
                   FROM v2_observation_outcomes o
                   WHERE o.status='COMPLETE' AND o.symbol=? AND o.net_return_pct IS NOT NULL
               )
               SELECT horizon_hours, COUNT(*) AS samples,
                      AVG(net_return_pct) AS expectancy_pct,
                      SUM(CASE WHEN net_return_pct>0 THEN 1 ELSE 0 END) AS wins,
                      SUM(CASE WHEN net_return_pct<0 THEN 1 ELSE 0 END) AS losses,
                      SUM(CASE WHEN net_return_pct=0 THEN 1 ELSE 0 END) AS breakevens,
                      SUM(CASE WHEN net_return_pct>0 THEN net_return_pct ELSE 0 END) /
                        NULLIF(ABS(SUM(CASE WHEN net_return_pct<0 THEN net_return_pct ELSE 0 END)),0) AS profit_factor
               FROM ranked WHERE rn=1
               GROUP BY horizon_hours ORDER BY CASE WHEN horizon_hours=? THEN 0 WHEN horizon_hours=1 THEN 1 ELSE 2 END, horizon_hours""",
            (sym, int(preferred_horizon)),
        ).fetchall()
        conn.close()
        row = dict(rows[0]) if rows else {}
        wins = int(row.get("wins") or 0)
        losses = int(row.get("losses") or 0)
        directional = wins + losses
        win_rate = wins / directional if directional else 0.0
        samples = int(row.get("samples") or 0)
        expectancy = float(row.get("expectancy_pct") or 0.0)
        pf = row.get("profit_factor")
        pf_value = float(pf) if pf is not None else (99.0 if wins and not losses else 0.0)
        enough = samples >= V2_MIN_SYMBOL_SAMPLES
        shadow_approved = enough and win_rate >= V2_MIN_WIN_RATE and pf_value >= V2_MIN_PROFIT_FACTOR and expectancy >= V2_MIN_EXPECTANCY_PCT
        recommendation = "APPROVE" if shadow_approved else ("BLOCK" if enough else "WATCH")
        return {
            "symbol": sym, "mode": "SHADOW", "horizonHours": int(row.get("horizon_hours") or preferred_horizon),
            "samples": samples, "wins": wins, "losses": losses, "breakevens": int(row.get("breakevens") or 0),
            "winRate": win_rate, "profitFactor": pf_value, "expectancyPct": expectancy,
            "recommendation": recommendation, "approved": shadow_approved,
            "reason": "forward evidence passes" if shadow_approved else ("insufficient forward samples" if not enough else "forward evidence below gate"),
        }
    except Exception as e:
        return {"symbol": sym, "mode": "SHADOW", "recommendation": "WATCH", "samples": 0, "error": str(e)}


def v2_symbol_expectancy(symbol: str):
    sym = str(symbol or "").upper().strip()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    cutoff = datetime.now(UTC) - timedelta(days=V2_LOOKBACK_DAYS)
    rows = []
    for trade in closed:
        if str(trade.get("symbol", "")).upper() != sym:
            continue
        dt = _parse_trade_dt(trade.get("timestamp"))
        if dt is not None and dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if dt is not None and dt < cutoff:
            continue
        rows.append(trade)

    pnls = [float(t.get("pnl") or 0.0) for t in rows]
    pct = [float(t.get("pnlPct") or 0.0) for t in rows]
    wins = [x for x in pnls if x > 0]
    losses = [x for x in pnls if x < 0]
    breakevens = [x for x in pnls if x == 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    directional = len(wins) + len(losses)
    win_rate = len(wins) / directional if directional else 0.0
    expectancy_pct = sum(pct) / len(pct) if pct else 0.0
    enough = len(rows) >= V2_MIN_SYMBOL_SAMPLES
    approved = enough and win_rate >= V2_MIN_WIN_RATE and profit_factor >= V2_MIN_PROFIT_FACTOR and expectancy_pct >= V2_MIN_EXPECTANCY_PCT
    reasons = []
    if not enough: reasons.append(f"only {len(rows)}/{V2_MIN_SYMBOL_SAMPLES} samples")
    if enough and win_rate < V2_MIN_WIN_RATE: reasons.append(f"win rate {win_rate:.0%} below {V2_MIN_WIN_RATE:.0%}")
    if enough and profit_factor < V2_MIN_PROFIT_FACTOR: reasons.append(f"profit factor {profit_factor:.2f} below {V2_MIN_PROFIT_FACTOR:.2f}")
    if enough and expectancy_pct < V2_MIN_EXPECTANCY_PCT: reasons.append(f"expectancy {expectancy_pct:.2f}% below {V2_MIN_EXPECTANCY_PCT:.2f}%")
    return {
        "symbol": sym, "samples": len(rows), "wins": len(wins), "losses": len(losses), "breakevens": len(breakevens),
        "directionalSamples": directional, "winRate": win_rate, "profitFactor": profit_factor,
        "expectancyPct": expectancy_pct, "totalPnl": sum(pnls),
        "approved": approved, "reason": "approved" if approved else "; ".join(reasons) or "not approved",
        "forwardShadow": v2_forward_shadow_profile(sym),
    }


def v2_trade_gate(scan: Dict[str, Any]):
    if not TRADEBOT_V2_ENABLED:
        return True, {"approved": True, "reason": "V2 disabled"}
    profile = v2_symbol_expectancy(scan.get("symbol"))
    # Deliberately use historical approval only. forwardShadow is advisory.
    return bool(profile.get("approved")), profile


# =========================
# TRADEBOT V2 SESSION / SAMPLE HELPERS
# =========================
def _v2_session_due_at(observed_at: datetime, horizon_hours: int) -> datetime:
    """Translate legacy horizon labels into tradable-session checkpoints.

    1 = one market hour; 24/72/120 = one/three/five trading sessions.
    Weekends are skipped and holidays are naturally deferred because evaluation
    only runs while Alpaca reports the market open.
    """
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    current = observed_at.astimezone(et)
    market_open = current.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = current.replace(hour=16, minute=0, second=0, microsecond=0)
    if current < market_open:
        current = market_open
    elif current > market_close:
        current = market_open + timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)

    if int(horizon_hours) == 1:
        due = current + timedelta(hours=1)
        if due > market_close:
            overflow = due - market_close
            due = (current + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
            while due.weekday() >= 5:
                due += timedelta(days=1)
            due += overflow
        return due.astimezone(UTC)

    sessions = max(1, int(round(int(horizon_hours) / 24)))
    due = current
    added = 0
    while added < sessions:
        due += timedelta(days=1)
        if due.weekday() < 5:
            added += 1
    return due.astimezone(UTC)


def _v2_sample_key(symbol: str, stage: str, decision: str, observed_at: datetime) -> str:
    bucket_seconds = max(60, V2_INDEPENDENT_SAMPLE_MINUTES * 60)
    bucket = int(observed_at.timestamp()) // bucket_seconds
    return f"{symbol}:{stage}:{decision}:{bucket}"

# =========================
# TRADEBOT V2 INTELLIGENCE LOG
# =========================
def _v2_decision_recently_logged(symbol: str, decision: str, stage: str) -> bool:
    if not SQLITE_ENABLED:
        return False
    try:
        init_db()
        cutoff = (datetime.now(UTC) - timedelta(seconds=V2_DECISION_DEDUPE_SECONDS)).isoformat()
        conn = db_connect()
        row = conn.execute(
            """SELECT id FROM v2_setup_decisions
               WHERE symbol=? AND decision=? AND stage=? AND timestamp>=?
               ORDER BY id DESC LIMIT 1""",
            (str(symbol).upper(), str(decision), str(stage), cutoff),
        ).fetchone()
        conn.close()
        return row is not None
    except Exception as e:
        print(f"V2 DECISION DEDUPE ERROR: {e}")
        return False


def record_v2_setup_decision(scan: Dict[str, Any], decision: str, stage: str, reason: str, profile: Optional[Dict[str, Any]] = None):
    if not (TRADEBOT_V2_ENABLED and V2_LOG_DECISIONS and SQLITE_ENABLED):
        return
    symbol = str(scan.get("symbol") or "").upper().strip()
    if not symbol or _v2_decision_recently_logged(symbol, decision, stage):
        return
    profile = profile or {}
    payload = {
        "confidenceLabel": scan.get("confidence_label"),
        "sniperReason": scan.get("sniper_reason"),
        "aPlusReason": scan.get("a_plus_reason"),
        "lockedToday": bool(scan.get("locked_today")),
        "v2": profile,
    }
    try:
        init_db()
        conn = db_connect()
        cur = conn.execute(
            """INSERT INTO v2_setup_decisions (
                timestamp, symbol, decision, stage, reason, price, confidence,
                quality, momentum, pullback, spread, ready_to_buy, sniper_pass,
                a_plus_pass, historical_samples, historical_win_rate,
                historical_profit_factor, historical_expectancy_pct, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                datetime.now(UTC).isoformat(), symbol, str(decision), str(stage), str(reason)[:1000],
                float(scan.get("price") or 0.0), float(scan.get("confidence") or 0.0),
                float(scan.get("quality_score") or 0.0), float(scan.get("short_momentum") or 0.0),
                float(scan.get("pullback") or 0.0), float(scan.get("spread") or 0.0),
                int(bool(scan.get("ready_to_buy"))), int(bool(scan.get("sniper_pass"))),
                int(bool(scan.get("a_plus_pass"))), int(profile.get("samples") or 0),
                float(profile.get("winRate") or 0.0), float(profile.get("profitFactor") or 0.0),
                float(profile.get("expectancyPct") or 0.0), json.dumps(payload, default=str),
            ),
        )
        decision_id = int(cur.lastrowid)
        observed_at = datetime.now(UTC)
        entry_price = float(scan.get("price") or 0.0)
        if decision_id > 0 and entry_price > 0:
            for horizon_hours in V2_OUTCOME_HORIZONS_HOURS:
                due_at = _v2_session_due_at(observed_at, int(horizon_hours))
                conn.execute(
                    """INSERT OR IGNORE INTO v2_observation_outcomes
                       (decision_id, symbol, observed_at, entry_price, horizon_hours, due_at, status, sample_key)
                       VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                    (decision_id, symbol, observed_at.isoformat(), entry_price, int(horizon_hours), due_at.isoformat(),
                     _v2_sample_key(symbol, str(stage), str(decision), observed_at)),
                )
        if decision_id > 0 and V4_MARKET_DNA_ENABLED:
            record_v4_market_dna(conn, decision_id, scan, decision, stage, reason, observed_at)
        if decision_id > 0 and globals().get("V9_ENABLED", False):
            try:
                _v9_capture_snapshot(conn, decision_id, scan, decision, stage, reason, observed_at)
            except Exception as v9_error:
                print(f"V9 SNAPSHOT ERROR {symbol}: {v9_error}")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"V2 DECISION LOG ERROR {symbol}: {e}")


def v2_recent_decisions(limit: int = 100):
    if not SQLITE_ENABLED:
        return []
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            "SELECT * FROM v2_setup_decisions ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"V2 RECENT DECISIONS ERROR: {e}")
        return []


def v2_setup_profiles(limit: int = 100):
    if not SQLITE_ENABLED:
        return []
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            """SELECT symbol,
                      COUNT(*) AS observations,
                      SUM(CASE WHEN decision='APPROVED' THEN 1 ELSE 0 END) AS approvals,
                      AVG(confidence) AS avg_confidence,
                      AVG(quality) AS avg_quality,
                      AVG(historical_win_rate) AS avg_historical_win_rate,
                      AVG(historical_profit_factor) AS avg_historical_profit_factor,
                      AVG(historical_expectancy_pct) AS avg_historical_expectancy_pct,
                      MAX(timestamp) AS last_seen
               FROM v2_setup_decisions
               GROUP BY symbol
               ORDER BY approvals DESC, observations DESC, symbol ASC
               LIMIT ?""",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"V2 SETUP PROFILES ERROR: {e}")
        return []


def v2_intelligence_summary():
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db()
        conn = db_connect()
        totals = conn.execute(
            """SELECT COUNT(*) AS observations,
                      COUNT(DISTINCT symbol) AS symbols,
                      SUM(CASE WHEN decision='APPROVED' THEN 1 ELSE 0 END) AS approvals,
                      SUM(CASE WHEN decision='REJECTED' THEN 1 ELSE 0 END) AS rejections,
                      MIN(timestamp) AS first_observation,
                      MAX(timestamp) AS last_observation
               FROM v2_setup_decisions"""
        ).fetchone()
        stages = conn.execute(
            """SELECT stage, COUNT(*) AS count
               FROM v2_setup_decisions GROUP BY stage ORDER BY count DESC"""
        ).fetchall()
        conn.close()
        data = dict(totals) if totals else {}
        observations = int(data.get("observations") or 0)
        approvals = int(data.get("approvals") or 0)
        return {
            "ok": True,
            **data,
            "approvalRate": approvals / observations if observations else 0.0,
            "stages": [dict(r) for r in stages],
            "recent": v2_recent_decisions(20),
            "profiles": v2_setup_profiles(20),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


# =========================
# TRADEBOT V2 STAGE 2 — FORWARD REPLAY / OUTCOMES
# =========================
def v2_seed_missing_outcomes(limit: int = 5000) -> int:
    """Create or repair pending outcomes using session-aware due dates."""
    if not SQLITE_ENABLED:
        return 0
    created = 0
    try:
        init_db()
        conn = db_connect()
        rows = conn.execute(
            """SELECT id, timestamp, symbol, price, decision, stage FROM v2_setup_decisions
               WHERE price > 0 ORDER BY id DESC LIMIT ?""",
            (max(1, min(int(limit), 50000)),),
        ).fetchall()
        for row in rows:
            try:
                observed_at = datetime.fromisoformat(str(row["timestamp"]).replace("Z", "+00:00"))
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=UTC)
                key = _v2_sample_key(str(row["symbol"]).upper(), str(row["stage"]), str(row["decision"]), observed_at)
                for horizon_hours in V2_OUTCOME_HORIZONS_HOURS:
                    due = _v2_session_due_at(observed_at, int(horizon_hours)).isoformat()
                    cur = conn.execute(
                        """INSERT OR IGNORE INTO v2_observation_outcomes
                           (decision_id, symbol, observed_at, entry_price, horizon_hours, due_at, status, sample_key)
                           VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?)""",
                        (int(row["id"]), str(row["symbol"]).upper(), observed_at.isoformat(),
                         float(row["price"]), int(horizon_hours), due, key),
                    )
                    created += int(cur.rowcount or 0)
                    conn.execute(
                        """UPDATE v2_observation_outcomes SET due_at=?, sample_key=COALESCE(sample_key, ?)
                           WHERE decision_id=? AND horizon_hours=? AND status='PENDING'""",
                        (due, key, int(row["id"]), int(horizon_hours)),
                    )
            except Exception as row_error:
                print(f"V2 OUTCOME SEED ROW ERROR: {row_error}")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"V2 OUTCOME SEED ERROR: {e}")
    return created

def _v6_parse_utc(value: Any) -> datetime:
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _v6_historical_checkpoint_price(symbol: str, due_at: Any) -> Dict[str, Any]:
    """Return the first one-minute bar at/after the intended checkpoint.

    A small look-back is requested to handle provider boundary behaviour, but a
    bar before due_at is used only when no later bar exists inside the allowed
    window. The selected timestamp and delay are always returned for validation.
    """
    due = _v6_parse_utc(due_at)
    start = due - timedelta(minutes=V6_HISTORICAL_BAR_LOOKBACK_MINUTES)
    end = due + timedelta(minutes=V6_HISTORICAL_BAR_LOOKAHEAD_MINUTES)
    request = StockBarsRequest(symbol_or_symbols=[symbol], timeframe=TimeFrame.Minute, start=start, end=end)
    response = data_client.get_stock_bars(request)
    try:
        bars = list(response[symbol])
    except Exception:
        data = getattr(response, "data", {}) or {}
        bars = list(data.get(symbol, []))
    if not bars:
        raise RuntimeError("historical_bar_unavailable")
    candidates=[]
    for bar in bars:
        ts=getattr(bar,"timestamp",None)
        close=getattr(bar,"close",None)
        if ts is None or close is None:
            continue
        bar_at=_v6_parse_utc(ts)
        candidates.append((bar_at,float(close)))
    if not candidates:
        raise RuntimeError("historical_bar_unavailable")
    after=[item for item in candidates if item[0] >= due]
    selected=min(after,key=lambda item:item[0]) if after else min(candidates,key=lambda item:abs((item[0]-due).total_seconds()))
    bar_at, price = selected
    delay_minutes=(bar_at-due).total_seconds()/60.0
    return {"price":price,"barAt":bar_at.isoformat(),"delayMinutes":delay_minutes,"source":"alpaca_historical_1min_close"}


def _v6_write_historical_outcome(conn: sqlite3.Connection, row: Any) -> Dict[str, Any]:
    symbol=str(row["symbol"]).upper()
    checkpoint=_v6_historical_checkpoint_price(symbol,row["due_at"])
    outcome_price=float(checkpoint["price"]); entry_price=float(row["entry_price"] or 0.0)
    if entry_price <= 0:
        raise RuntimeError("missing_or_invalid_entry_price")
    return_pct=((outcome_price/entry_price)-1.0)*100.0
    estimated_cost_pct=max(0.0,V2_ESTIMATED_COST_BPS/100.0)
    net_return_pct=return_pct-estimated_cost_pct
    now=datetime.now(UTC).isoformat()
    conn.execute("""UPDATE v2_observation_outcomes
       SET evaluated_at=?, outcome_price=?, return_pct=?, net_return_pct=?, estimated_cost_pct=?,
           evaluation_delay_minutes=?, outcome_bar_at=?, outcome_source=?, repaired_at=?, status='COMPLETE', error=NULL
       WHERE id=?""",
       (checkpoint["barAt"],outcome_price,return_pct,net_return_pct,estimated_cost_pct,
        float(checkpoint["delayMinutes"]),checkpoint["barAt"],checkpoint["source"],now,int(row["id"])))
    return checkpoint


def v2_evaluate_due_outcomes(limit: Optional[int] = None) -> Dict[str, Any]:
    """Evaluate due outcomes at their historical checkpoint, never at the worker's current quote."""
    if not (TRADEBOT_V2_ENABLED and SQLITE_ENABLED):
        return {"ok":False,"evaluated":0,"reason":"V2 or SQLite disabled"}
    batch=max(1,min(int(limit or V2_OUTCOME_BATCH_SIZE),1000)); evaluated=0; errors=0
    try:
        init_db(); conn=db_connect()
        rows=conn.execute("""SELECT * FROM v2_observation_outcomes
            WHERE status='PENDING' AND due_at<=? ORDER BY due_at ASC LIMIT ?""",
            (datetime.now(UTC).isoformat(),batch)).fetchall()
        for row in rows:
            try:
                _v6_write_historical_outcome(conn,row); evaluated += 1
            except Exception as row_error:
                errors += 1
                conn.execute("UPDATE v2_observation_outcomes SET error=? WHERE id=?",(str(row_error)[:500],int(row["id"])))
        conn.commit(); conn.close()
        if evaluated or errors: print(f"V6.4 OUTCOMES | historical={evaluated} errors={errors}")
        return {"ok":True,"version":"V6.4","evaluated":evaluated,"errors":errors,"due":len(rows),
                "outcomeSource":"alpaca_historical_1min_close"}
    except Exception as e:
        try: conn.close()
        except Exception: pass
        return {"ok":False,"version":"V6.4","evaluated":evaluated,"errors":errors+1,"error":str(e)}


def v6_repair_outcome_times(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = V6_REPAIR_BATCH_SIZE) -> Dict[str, Any]:
    """Repair legacy live-quote outcomes using the intended historical due_at checkpoint."""
    horizon=max(1,int(horizon_hours)); batch=max(1,min(int(limit),1000)); repaired=0; errors=0; samples=[]
    try:
        init_db(); conn=db_connect()
        rows=conn.execute("""SELECT * FROM v2_observation_outcomes
            WHERE horizon_hours=? AND status='COMPLETE'
              AND (outcome_source IS NULL OR outcome_source!='alpaca_historical_1min_close' OR outcome_bar_at IS NULL)
            ORDER BY due_at ASC LIMIT ?""",(horizon,batch)).fetchall()
        for row in rows:
            try:
                cp=_v6_write_historical_outcome(conn,row); repaired += 1
                if len(samples)<10: samples.append({"id":int(row["id"]),"symbol":row["symbol"],"dueAt":row["due_at"],**cp})
            except Exception as exc:
                errors += 1
                conn.execute("UPDATE v2_observation_outcomes SET error=? WHERE id=?",(str(exc)[:500],int(row["id"])))
        conn.commit()
        remaining=int(conn.execute("""SELECT COUNT(*) FROM v2_observation_outcomes
            WHERE horizon_hours=? AND status='COMPLETE'
              AND (outcome_source IS NULL OR outcome_source!='alpaca_historical_1min_close' OR outcome_bar_at IS NULL)""",(horizon,)).fetchone()[0])
        conn.close()
        return {"ok":True,"version":"V6.4","advisoryOnly":True,"horizonHours":horizon,"processed":len(rows),
                "repaired":repaired,"errors":errors,"remaining":remaining,"samples":samples,
                "note":"Research outcomes only were repaired. Live trading logic was unchanged."}
    except Exception as e:
        try: conn.close()
        except Exception: pass
        return {"ok":False,"version":"V6.4","error":str(e),"repaired":repaired,"errors":errors+1}


def v2_normalise_reason(reason: str) -> str:
    """Collapse highly specific numeric rejection messages into useful evidence buckets."""
    raw = str(reason or "").strip().lower()
    if not raw:
        return "unspecified"

    def bucket(value: float, width: float, decimals: int = 2) -> str:
        low = (value // width) * width
        high = low + width
        return f"{low:.{decimals}f} to {high:.{decimals}f}"

    match = re.search(r"confidence(?: too low)?\s+(-?\d+(?:\.\d+)?)", raw)
    if match:
        value = float(match.group(1))
        return f"confidence {bucket(value, 0.10, 2)}"

    match = re.search(r"quality(?: too low)?\s+(-?\d+(?:\.\d+)?)", raw)
    if match:
        value = float(match.group(1))
        return f"quality {bucket(value, 0.005, 3)}"

    match = re.search(r"momentum (?:negative|too weak)\s+(-?\d+(?:\.\d+)?)", raw)
    if match:
        value = float(match.group(1))
        return f"momentum {bucket(value, 0.001, 3)}"

    match = re.search(r"pullback outside sniper range\s+(-?\d+(?:\.\d+)?)", raw)
    if match:
        value = float(match.group(1))
        return f"pullback {bucket(value, 0.005, 3)} outside range"

    match = re.search(r"only\s+(\d+)/(\d+)\s+samples", raw)
    if match:
        have, need = int(match.group(1)), int(match.group(2))
        return f"insufficient samples {have}/{need}"

    if "win rate" in raw or "profit factor" in raw or "expectancy" in raw:
        failures = []
        if "win rate" in raw: failures.append("win rate")
        if "profit factor" in raw: failures.append("profit factor")
        if "expectancy" in raw: failures.append("expectancy")
        return "expectancy gate: " + " + ".join(failures)

    if "already holding" in raw:
        return "already holding"
    if "all v2 gates passed" in raw:
        return "all V2 gates passed"
    return raw[:160]


def v2_outcomes_summary(symbol: Optional[str] = None) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db()
        conn = db_connect()
        params: List[Any] = []
        symbol_clause = ""
        if symbol:
            symbol_clause = " AND o.symbol=?"
            params.append(str(symbol).upper())
        totals = conn.execute(
            f"""SELECT COUNT(*) AS scheduled,
                       SUM(CASE WHEN o.status='COMPLETE' THEN 1 ELSE 0 END) AS completed,
                       SUM(CASE WHEN o.status='PENDING' THEN 1 ELSE 0 END) AS pending,
                       COUNT(DISTINCT o.symbol) AS symbols
                FROM v2_observation_outcomes o WHERE 1=1 {symbol_clause}""", params
        ).fetchone()
        cte = f"""WITH ranked AS (
                    SELECT o.*, d.stage, d.decision, d.reason,
                           CASE
                             WHEN lower(d.reason) LIKE 'confidence%' THEN 'confidence threshold'
                             WHEN lower(d.reason) LIKE 'quality%' THEN 'quality threshold'
                             WHEN lower(d.reason) LIKE 'momentum negative%' THEN 'negative momentum'
                             WHEN lower(d.reason) LIKE 'momentum too weak%' THEN 'weak momentum'
                             WHEN lower(d.reason) LIKE 'pullback outside%' THEN 'pullback outside range'
                             WHEN lower(d.reason) LIKE 'only % samples%' THEN 'insufficient samples'
                             WHEN lower(d.reason) LIKE 'win rate%' OR lower(d.reason) LIKE 'profit factor%' OR lower(d.reason) LIKE 'expectancy%' THEN 'expectancy evidence below gate'
                             WHEN lower(d.reason) LIKE '%already holding%' THEN 'already holding'
                             ELSE d.reason
                           END AS reason_bucket,
                           ROW_NUMBER() OVER (PARTITION BY COALESCE(o.sample_key, CAST(o.decision_id AS TEXT)), o.horizon_hours
                                              ORDER BY o.id ASC) AS rn
                    FROM v2_observation_outcomes o
                    JOIN v2_setup_decisions d ON d.id=o.decision_id
                    WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL {symbol_clause}
                 )"""
        metric_sql = """COUNT(*) AS samples,
                       SUM(CASE WHEN net_return_pct>0 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN net_return_pct<0 THEN 1 ELSE 0 END) AS losses,
                       SUM(CASE WHEN net_return_pct=0 THEN 1 ELSE 0 END) AS breakevens,
                       AVG(net_return_pct) AS avg_return_pct,
                       SUM(CASE WHEN net_return_pct>0 THEN 1 ELSE 0 END)*1.0/
                         NULLIF(SUM(CASE WHEN net_return_pct<>0 THEN 1 ELSE 0 END),0) AS win_rate,
                       AVG(CASE WHEN net_return_pct>0 THEN net_return_pct END) AS avg_win_pct,
                       AVG(CASE WHEN net_return_pct<0 THEN net_return_pct END) AS avg_loss_pct,
                       MIN(net_return_pct) AS worst_return_pct, MAX(net_return_pct) AS best_return_pct,
                       SUM(CASE WHEN net_return_pct>0 THEN net_return_pct ELSE 0 END) /
                         NULLIF(ABS(SUM(CASE WHEN net_return_pct<0 THEN net_return_pct ELSE 0 END)),0) AS profit_factor,
                       AVG(net_return_pct) AS expectancy_pct"""
        profiles = conn.execute(
            cte + f" SELECT horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY horizon_hours ORDER BY horizon_hours", params
        ).fetchall()
        by_stage = conn.execute(
            cte + f" SELECT stage, decision, horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY stage, decision, horizon_hours ORDER BY horizon_hours, samples DESC", params
        ).fetchall()
        by_reason = conn.execute(
            cte + f" SELECT stage, decision, reason, horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY stage, decision, reason, horizon_hours ORDER BY horizon_hours, samples DESC", params
        ).fetchall()
        by_reason_bucket = conn.execute(
            cte + f" SELECT stage, decision, reason_bucket AS reason, horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY stage, decision, reason_bucket, horizon_hours ORDER BY horizon_hours, samples DESC", params
        ).fetchall()
        by_symbol = conn.execute(
            cte + f" SELECT symbol, stage, decision, horizon_hours, {metric_sql} FROM ranked WHERE rn=1 GROUP BY symbol, stage, decision, horizon_hours ORDER BY horizon_hours, samples DESC", params
        ).fetchall()
        conn.close()
        symbols_for_shadow = sorted({str(r["symbol"]) for r in by_symbol})
        shadow = [v2_forward_shadow_profile(sym) for sym in symbols_for_shadow]
        return {"ok": True, **(dict(totals) if totals else {}),
                "winRateDefinition": "wins / (wins + losses); breakevens excluded",
                "independentSampleMinutes": V2_INDEPENDENT_SAMPLE_MINUTES,
                "estimatedRoundTripCostBps": V2_ESTIMATED_COST_BPS,
                "horizonMeaning": {"1": "one market hour", "24": "one trading session", "72": "three trading sessions", "120": "five trading sessions"},
                "horizons": [dict(r) for r in profiles], "byStage": [dict(r) for r in by_stage],
                "byReason": [dict(r) for r in by_reason],
                "byReasonBucket": [dict(r) for r in by_reason_bucket], "bySymbol": [dict(r) for r in by_symbol],
                "shadowRecommendations": shadow,
                "shadowMode": True,
                "shadowNote": "Forward recommendations are advisory and do not alter live approvals.",
                "evidencePatch": {"reasonBuckets": True, "safeTrustRatings": True, "proposedQtyAudit": True}}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def v2_replay_rows(symbol: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    try:
        init_db()
        conn = db_connect()
        params: List[Any] = []
        where = ""
        if symbol:
            where = "WHERE d.symbol=?"
            params.append(str(symbol).upper())
        params.append(max(1, min(int(limit), 2000)))
        rows = conn.execute(
            f"""SELECT d.id AS decision_id, d.timestamp, d.symbol, d.decision, d.stage,
                       d.reason, d.price AS entry_price, d.confidence, d.quality,
                       d.momentum, d.pullback, o.horizon_hours, o.status,
                       o.due_at, o.evaluated_at, o.outcome_price, o.return_pct,
                       o.net_return_pct, o.estimated_cost_pct, o.sample_key
                FROM v2_setup_decisions d
                LEFT JOIN v2_observation_outcomes o ON o.decision_id=d.id
                {where}
                ORDER BY d.id DESC, o.horizon_hours ASC LIMIT ?""", params
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"V2 REPLAY ERROR: {e}")
        return []

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
            record_v2_setup_decision(scan, "REJECTED", "account_gate", reason)
            continue
        if PDT_AWARE_MODE_ENABLED and today_buy_count() >= MAX_NEW_BUYS_PER_DAY_PDT_AWARE:
            record_v2_setup_decision(scan, "REJECTED", "pdt_gate", "maximum new buys for today reached")
            continue
        sniper_ok, sniper_reason = sniper_passes(scan)
        if not sniper_ok:
            print(f"SNIPER SKIP {symbol} | {sniper_reason}")
            record_v2_setup_decision(scan, "REJECTED", "sniper_gate", sniper_reason)
            continue

        aplus_ok, aplus_reason = a_plus_gate(scan)
        if not aplus_ok:
            print(f"A+ SKIP {symbol} | {aplus_reason}")
            record_v2_setup_decision(scan, "REJECTED", "a_plus_gate", aplus_reason)
            continue
        if not scan["ready_to_buy"]:
            record_v2_setup_decision(scan, "REJECTED", "trigger_gate", "entry trigger not ready")
            continue
        v2_ok, v2_profile = v2_trade_gate(scan)
        if not v2_ok:
            print(f"V2 SKIP {symbol} | {v2_profile.get('reason')}")
            record_v2_setup_decision(scan, "REJECTED", "expectancy_gate", v2_profile.get("reason", "not approved"), v2_profile)
            continue
        scan["v2Expectancy"] = v2_profile
        record_v2_setup_decision(scan, "APPROVED", "final_gate", "all V2 gates passed", v2_profile)
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
            ai_block, ai_reason = hold_ai_blocks_soft_exit(p, "PARTIAL PROFIT TAKE")
            if ai_block:
                print(ai_reason)
                continue
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
            ai_block, ai_reason = hold_ai_blocks_soft_exit(p, "STALL EXIT")
            if ai_block:
                print(ai_reason)
                continue
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
                ai_block, ai_reason = hold_ai_blocks_soft_exit(p, "MONEY MODE TRAILING PROFIT")
                if ai_block:
                    print(ai_reason)
                    continue
                try:
                    if pdt_aware_should_avoid_sell(symbol, "MONEY MODE TRAILING PROFIT", p["pnlPct"]):
                        continue

                    market_sell_qty(symbol, qty, entry=entry, price=price, reason="MONEY MODE TRAILING PROFIT")
                    state[symbol]["highest_since_entry"] = None
                except Exception as e:
                    print(f"SELL ERROR {symbol}: {e}")
                continue

def money_mode_buy(scans, manual=False):
    if TRADEBOT_V2_ENABLED and not PAPER and not TRADEBOT_V2_LIVE_ENABLED:
        # Validation mode must still run the complete decision pipeline so V2 can
        # record approved/rejected observations without submitting a live order.
        try:
            validation_picks = pick_money_mode_stocks(scans)
            print(f"V2 VALIDATION | observations processed={len(scans)} approved={len(validation_picks)} live_order=False")
        except Exception as e:
            print(f"V2 VALIDATION LOG ERROR: {e}")
        return "BUY BLOCKED | TradeBot V2 validation mode. Decisions recorded; live ordering remains disabled."
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
    if TRADEBOT_V2_ENABLED and not PAPER and not TRADEBOT_V2_LIVE_ENABLED:
        return {"ok": False, "message": "TradeBot V2 validation mode blocks new live buys."}
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_setup_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            decision TEXT NOT NULL,
            stage TEXT,
            reason TEXT,
            price REAL,
            confidence REAL,
            quality REAL,
            momentum REAL,
            pullback REAL,
            spread REAL,
            ready_to_buy INTEGER,
            sniper_pass INTEGER,
            a_plus_pass INTEGER,
            historical_samples INTEGER,
            historical_win_rate REAL,
            historical_profit_factor REAL,
            historical_expectancy_pct REAL,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_setup_decisions_symbol_time
        ON v2_setup_decisions(symbol, timestamp)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_setup_decisions_decision
        ON v2_setup_decisions(decision)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_observation_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            entry_price REAL NOT NULL,
            horizon_hours INTEGER NOT NULL,
            due_at TEXT NOT NULL,
            evaluated_at TEXT,
            outcome_price REAL,
            return_pct REAL,
            net_return_pct REAL,
            estimated_cost_pct REAL,
            sample_key TEXT,
            status TEXT NOT NULL DEFAULT 'PENDING',
            error TEXT,
            UNIQUE(decision_id, horizon_hours)
        )
    """)
    for column_sql in (
        "ALTER TABLE v2_observation_outcomes ADD COLUMN net_return_pct REAL",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN estimated_cost_pct REAL",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN sample_key TEXT",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN evaluation_delay_minutes REAL",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN outcome_bar_at TEXT",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN outcome_source TEXT",
        "ALTER TABLE v2_observation_outcomes ADD COLUMN repaired_at TEXT",
    ):
        try:
            cur.execute(column_sql)
        except Exception:
            pass

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_outcomes_due
        ON v2_observation_outcomes(status, due_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_outcomes_symbol
        ON v2_observation_outcomes(symbol, horizon_hours)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v4_market_dna (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decision_id INTEGER NOT NULL UNIQUE,
            observed_at TEXT NOT NULL,
            symbol TEXT NOT NULL,
            decision TEXT NOT NULL,
            stage TEXT,
            reason TEXT,
            market_regime TEXT,
            session_name TEXT,
            weekday INTEGER,
            hour_utc INTEGER,
            price REAL,
            confidence REAL,
            quality REAL,
            momentum REAL,
            pullback REAL,
            spread REAL,
            ready_to_buy INTEGER,
            sniper_pass INTEGER,
            a_plus_pass INTEGER,
            spy_move REAL,
            qqq_move REAL,
            position_count INTEGER,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v4_dna_symbol_time
        ON v4_market_dna(symbol, observed_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v4_dna_decision
        ON v4_market_dna(decision, stage)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v5_replay_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            label TEXT,
            date_from TEXT,
            date_to TEXT,
            horizon_hours INTEGER NOT NULL,
            observation_count INTEGER NOT NULL DEFAULT 0,
            variant_count INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v5_replay_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            variant_key TEXT NOT NULL,
            variant_name TEXT NOT NULL,
            trades INTEGER NOT NULL DEFAULT 0,
            wins INTEGER NOT NULL DEFAULT 0,
            losses INTEGER NOT NULL DEFAULT 0,
            win_rate REAL,
            profit_factor REAL,
            expectancy_pct REAL,
            total_return_pct REAL,
            max_drawdown_pct REAL,
            largest_win_pct REAL,
            largest_loss_pct REAL,
            config_json TEXT,
            UNIQUE(run_id, variant_key)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v5_replay_runs_created
        ON v5_replay_runs(created_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v5_replay_results_run
        ON v5_replay_results(run_id, expectancy_pct)
    """)


    # V6.1 multi-brain shadow intelligence. These tables never drive live orders.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v6_brain_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brain_key TEXT NOT NULL,
            brain_name TEXT NOT NULL,
            decision_id INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            market_regime TEXT,
            horizon_hours INTEGER NOT NULL,
            accepted INTEGER NOT NULL DEFAULT 0,
            return_pct REAL,
            confidence REAL,
            quality REAL,
            momentum REAL,
            pullback REAL,
            spread REAL,
            config_json TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(brain_key, decision_id, horizon_hours)
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v6_brain_results
        ON v6_brain_observations(brain_key, horizon_hours, accepted, observed_at)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v6_brain_regime
        ON v6_brain_observations(market_regime, brain_key, horizon_hours)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v6_recommendations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            horizon_hours INTEGER NOT NULL,
            market_regime TEXT,
            current_brain TEXT,
            recommended_brain TEXT,
            confidence_grade TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            payload_json TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_optimizer_evaluations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluated_at TEXT NOT NULL,
            horizon_hours INTEGER NOT NULL,
            candidate_confidence REAL,
            candidate_quality REAL,
            current_confidence REAL,
            current_quality REAL,
            eligible INTEGER DEFAULT 0,
            stable_key TEXT,
            payload_json TEXT
        )
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_v2_optimizer_eval_time
        ON v2_optimizer_evaluations(evaluated_at)
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS v2_strategy_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            version_label TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence REAL NOT NULL,
            quality REAL NOT NULL,
            previous_confidence REAL,
            previous_quality REAL,
            reason TEXT,
            metrics_json TEXT,
            rollback_of INTEGER
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
            INSERT OR REPLACE INTO trades (
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
            ORDER BY timestamp DESC
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
    wins = [t for t in closed if float(t.get("pnl") or 0.0) > 0]
    losses = [t for t in closed if float(t.get("pnl") or 0.0) < 0]
    breakevens = [t for t in closed if float(t.get("pnl") or 0.0) == 0]
    total_pnl = sum(float(t.get("pnl") or 0.0) for t in closed)
    total_pnl_gbp = sum(float(t.get("pnlGbp") or 0.0) for t in closed)

    return {
        "closedTrades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "breakevens": len(breakevens),
        "winRate": len(wins) / max(1, len(wins) + len(losses)),
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
    """Return clean BUY/SELL even when alpaca-py gives an enum like OrderSide.BUY."""
    raw = getattr(order, "side", "")
    value = getattr(raw, "value", raw)
    text = str(value).upper().strip()
    if "." in text:
        text = text.split(".")[-1]
    if text in ("BUY", "SELL"):
        return text
    return text


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
            side = get_order_side(order)
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
    wins = [t for t in closed if float(t.get("pnl") or 0.0) > 0]
    losses = [t for t in closed if float(t.get("pnl") or 0.0) < 0]
    breakevens = [t for t in closed if float(t.get("pnl") or 0.0) == 0]
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
        row = by_symbol.setdefault(symbol, {
            "symbol": symbol, "trades": 0, "wins": 0, "losses": 0, "breakevens": 0,
            "totalPnl": 0.0, "totalPnlGbp": 0.0, "grossProfit": 0.0, "grossLoss": 0.0,
            "winRate": 0.0, "avgPnl": 0.0, "profitFactor": 0.0, "trust": "NEW"
        })
        pnl = float(t.get("pnl") or 0.0)
        row["trades"] += 1
        row["totalPnl"] += pnl
        row["totalPnlGbp"] += float(t.get("pnlGbp") or 0.0)
        if pnl > 0:
            row["wins"] += 1
            row["grossProfit"] += pnl
        elif pnl < 0:
            row["losses"] += 1
            row["grossLoss"] += abs(pnl)
        else:
            row["breakevens"] += 1

    rows = []
    for row in by_symbol.values():
        directional = row["wins"] + row["losses"]
        row["winRate"] = row["wins"] / directional if directional else 0.0
        row["avgPnl"] = row["totalPnl"] / max(1, row["trades"])
        row["profitFactor"] = row["grossProfit"] / row["grossLoss"] if row["grossLoss"] > 0 else (99.0 if row["grossProfit"] > 0 else 0.0)

        enough_boost = row["trades"] >= AUTO_BOOST_MIN_TRADES
        enough_blacklist = row["trades"] >= AUTO_BLACKLIST_MIN_TRADES
        if enough_blacklist and row["totalPnl"] < 0 and row["profitFactor"] < 0.75:
            row["trust"] = "BLACKLIST"
        elif row["trades"] >= 3 and (row["totalPnl"] <= 0 or row["profitFactor"] < 1.0):
            row["trust"] = "REDUCE"
        elif enough_boost and row["winRate"] >= AUTO_BOOST_MIN_WINRATE and row["totalPnl"] >= AUTO_BOOST_MIN_TOTAL_PNL and row["profitFactor"] >= 1.20:
            row["trust"] = "BOOST"
        elif row["trades"] >= 3:
            row["trust"] = "NEUTRAL"
        rows.append(row)

    return {
        "enabled": ANALYTICS_ENABLED,
        "closedTrades": len(closed), "wins": len(wins), "losses": len(losses), "breakevens": len(breakevens),
        "winRate": len(wins) / max(1, len(wins) + len(losses)),
        "totalPnl": total_pnl, "totalPnlGbp": total_pnl_gbp,
        "averageWin": avg_win, "averageLoss": avg_loss,
        "averageWinGbp": avg_win_gbp, "averageLossGbp": avg_loss_gbp,
        "profitFactor": gross_win / max(0.01, gross_loss),
        "trustDefinition": "BOOST requires positive PnL and PF >= 1.20; negative PnL/PF < 1 becomes REDUCE or BLACKLIST",
        "bestStocks": sorted(rows, key=lambda x: (x["totalPnl"], x["profitFactor"]), reverse=True)[:10],
        "worstStocks": sorted(rows, key=lambda x: (x["totalPnl"], x["profitFactor"]))[:10],
        "todayRealisedPnl": today_realised_pnl(), "todayRealisedPnlGbp": today_realised_pnl_gbp(),
    }


def symbol_stats(symbol: str):
    symbol = symbol.upper()
    closed = closed_trades_from_db(10000) if "closed_trades_from_db" in globals() else []
    trades = [t for t in closed if str(t.get("symbol", "")).upper() == symbol]
    pnls = [float(t.get("pnl") or 0.0) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    breakevens = [p for p in pnls if p == 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    directional = len(wins) + len(losses)
    return {
        "symbol": symbol, "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "breakevens": len(breakevens), "winRate": len(wins) / directional if directional else 0.0,
        "totalPnl": sum(pnls), "avgPnl": sum(pnls) / max(1, len(pnls)),
        "profitFactor": gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0),
    }


def auto_improve_decision(symbol: str):
    if not AUTO_IMPROVE_ENABLED:
        return {"action": "NORMAL", "multiplier": 1.0, "reason": "auto improve off"}
    row = symbol_stats(symbol)
    trades = int(row.get("trades") or 0)
    win_rate = float(row.get("winRate") or 0.0)
    total_pnl = float(row.get("totalPnl") or 0.0)
    profit_factor = float(row.get("profitFactor") or 0.0)

    if AUTO_BLACKLIST_ENABLED and trades >= AUTO_BLACKLIST_MIN_TRADES and total_pnl < 0 and profit_factor < 0.75:
        return {"action": "BLACKLIST", "multiplier": 0.0,
                "reason": f"weak history: trades={trades}, winRate={win_rate:.2f}, PF={profit_factor:.2f}, pnl=${total_pnl:.2f}"}
    if trades >= 3 and (total_pnl <= 0 or profit_factor < 1.0):
        return {"action": "REDUCE", "multiplier": AUTO_REDUCE_MULTIPLIER,
                "reason": f"negative expectancy: trades={trades}, winRate={win_rate:.2f}, PF={profit_factor:.2f}, pnl=${total_pnl:.2f}"}
    if AUTO_BOOST_ENABLED and trades >= AUTO_BOOST_MIN_TRADES and win_rate >= AUTO_BOOST_MIN_WINRATE and total_pnl >= AUTO_BOOST_MIN_TOTAL_PNL and profit_factor >= 1.20:
        return {"action": "BOOST", "multiplier": AUTO_BOOST_MULTIPLIER,
                "reason": f"strong history: trades={trades}, winRate={win_rate:.2f}, PF={profit_factor:.2f}, pnl=${total_pnl:.2f}"}
    return {"action": "NORMAL", "multiplier": 1.0,
            "reason": f"normal history: trades={trades}, PF={profit_factor:.2f}, pnl=${total_pnl:.2f}"}


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
    Build the weekly watchlist from closed-trade memory using the same PnL/PF
    rules as the live optimiser. BLACKLIST symbols are excluded from new-entry
    selection even when an older saved universe still labels them as GOOD.
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
        symbol = str(m.get("symbol", "")).upper().strip()
        if not symbol:
            continue

        stats = symbol_stats(symbol)
        decision = auto_improve_decision(symbol)
        action = str(decision.get("action") or "NORMAL").upper()

        # A currently held symbol must remain visible for position management,
        # but a BLACKLIST symbol must never be selected for a fresh entry.
        held_qty = 0.0
        try:
            held_qty, _ = get_position(symbol)
            held_qty = float(held_qty or 0.0)
        except Exception:
            held_qty = 0.0

        if action == "BLACKLIST" and held_qty <= DUST_THRESHOLD:
            continue

        trades = int(stats.get("trades") or 0)
        win_rate = float(stats.get("winRate") or 0.0)
        avg_pnl = float(stats.get("avgPnl") or 0.0)
        total_pnl = float(stats.get("totalPnl") or 0.0)
        profit_factor = float(stats.get("profitFactor") or 0.0)

        score = 0.0
        score += min(trades, 20) * 0.6
        score += win_rate * 12.0
        score += avg_pnl * 3.0
        score += max(-10.0, min(10.0, total_pnl)) * 0.5
        score += min(profit_factor, 4.0) * 1.5

        if action == "BOOST":
            score += 6.0
        elif action == "REDUCE":
            score -= 8.0
        elif action == "BLACKLIST":
            score -= 100.0

        management_only = action == "BLACKLIST" and held_qty > DUST_THRESHOLD
        reason = (
            f"trust {action} | trades={trades} | winRate={win_rate*100:.2f}% | "
            f"PF={profit_factor:.2f} | avgPnL=${avg_pnl:.2f} | totalPnL=${total_pnl:.2f}"
        )
        if management_only:
            reason = "currently held; management only | " + reason

        rows.append({
            "symbol": symbol,
            "score": round(score, 4),
            "reason": reason,
            "status": "active",
            "trust": action,
            "profitFactor": profit_factor,
            "totalPnl": total_pnl,
            "eligibleForNewBuy": not management_only and action != "BLACKLIST",
            "managementOnly": management_only,
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    return rows


def reconcile_auto_universe_rows(rows, target_size=None):
    """Re-score saved universe rows with current optimiser evidence.

    This repairs stale weekly labels immediately after a deployment. Symbols
    currently classified BLACKLIST are removed from new-entry selection. Open
    positions are retained as management-only rows so exit logic can still see
    them. Empty slots are filled from the candidate pool with non-blacklisted
    symbols.
    """
    target_size = int(target_size or AUTO_UNIVERSE_SIZE)
    result = []
    seen = set()

    def append_symbol(symbol, original=None):
        symbol = str(symbol or "").upper().strip()
        if not symbol or symbol in seen:
            return

        decision = auto_improve_decision(symbol)
        action = str(decision.get("action") or "NORMAL").upper()
        stats = symbol_stats(symbol)
        held_qty = 0.0
        try:
            held_qty, _ = get_position(symbol)
            held_qty = float(held_qty or 0.0)
        except Exception:
            pass

        management_only = action == "BLACKLIST" and held_qty > DUST_THRESHOLD
        if action == "BLACKLIST" and not management_only:
            return

        original = original or {}
        score = float(original.get("score") or 0.0)
        if action == "BOOST":
            score += 6.0
        elif action == "REDUCE":
            score -= 8.0
        elif management_only:
            score = max(score, 20.0)

        reason = (
            f"trust {action} | trades={int(stats.get('trades') or 0)} | "
            f"winRate={float(stats.get('winRate') or 0.0)*100:.2f}% | "
            f"PF={float(stats.get('profitFactor') or 0.0):.2f} | "
            f"avgPnL=${float(stats.get('avgPnl') or 0.0):.2f} | "
            f"totalPnL=${float(stats.get('totalPnl') or 0.0):.2f}"
        )
        if management_only:
            reason = "currently held; management only | " + reason

        result.append({
            **original,
            "symbol": symbol,
            "score": round(score, 4),
            "reason": reason,
            "status": "active",
            "trust": action,
            "profitFactor": float(stats.get("profitFactor") or 0.0),
            "totalPnl": float(stats.get("totalPnl") or 0.0),
            "eligibleForNewBuy": not management_only and action != "BLACKLIST",
            "managementOnly": management_only,
        })
        seen.add(symbol)

    for row in rows or []:
        append_symbol(row.get("symbol"), row)

    # Refill removed BLACKLIST slots from the current memory ranking first.
    for row in universe_rows_from_stock_memory():
        if len(result) >= target_size:
            break
        append_symbol(row.get("symbol"), row)

    # Then use the normal candidate pool, still respecting BLACKLIST evidence.
    for symbol in AUTO_UNIVERSE_CANDIDATE_POOL:
        if len(result) >= target_size:
            break
        append_symbol(symbol, score_candidate_symbol(symbol))

    result.sort(key=lambda r: float(r.get("score") or 0.0), reverse=True)
    return result[:target_size]

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

    chosen = reconcile_auto_universe_rows(chosen, AUTO_UNIVERSE_SIZE)
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
    global current_universe
    active = get_weekly_universe_from_db()

    # If DB has not been populated yet but stock memory exists, show live preview.
    if not active:
        active = universe_rows_from_stock_memory()[:AUTO_UNIVERSE_SIZE]

    # Always re-score saved rows against current optimiser evidence. This makes
    # stale GOOD labels disappear immediately after deployment and suppresses
    # BLACKLIST symbols without waiting for the next weekly refresh.
    active = reconcile_auto_universe_rows(active, AUTO_UNIVERSE_SIZE)
    symbols = [r["symbol"] for r in active]
    if symbols:
        current_universe = symbols[:]
        for symbol in current_universe:
            ensure_symbol_state(symbol, custom=symbol in custom_symbols)

    return {
        "enabled": AUTO_UNIVERSE_ENABLED,
        "size": len(active),
        "configuredSize": AUTO_UNIVERSE_SIZE,
        "weekStart": week_start_str(),
        "activeSymbols": symbols if active else list(current_universe),
        "rows": active,
        "lastRefresh": get_last_universe_refresh(),
        "candidatePoolSize": len(AUTO_UNIVERSE_CANDIDATE_POOL),
        "keepWinners": True,
        "liveRescored": True,
        "blacklistSuppressed": True,
        "trustDefinition": "BOOST/REDUCE/BLACKLIST uses current PnL and profit factor; BLACKLIST symbols are excluded from new entries",
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
        "strategySettings": current_strategy_settings_payload() if "current_strategy_settings_payload" in globals() else {},
        "aPlusMinConfidence": A_PLUS_MIN_CONFIDENCE,
        "aPlusMinQuality": A_PLUS_MIN_QUALITY,
        "tempBlacklist": temp_blacklist,
        "todayBuyCount": today_buy_count(),
        "maxNewBuysPerDayPdtAware": MAX_NEW_BUYS_PER_DAY_PDT_AWARE,
        "lockedSymbolsToday": locked_symbols,
        "customSymbols": sorted(list(custom_symbols.keys())),
        "maxPositions": MAX_POSITIONS,
        "positionSettings": current_position_settings_payload() if "current_position_settings_payload" in globals() else {},
        "newPositionNotional": calculate_new_position_notional(),
        "allowedNewPositions": allowed_new_position_count(),
        "universe": list(current_universe),
        "config": {
            "checkInterval": CHECK_INTERVAL,
            "maxPositions": MAX_POSITIONS,
            "fullBuyWhenOnePosition": FULL_BUY_WHEN_ONE_POSITION,
            "fullBuyCashBuffer": FULL_BUY_CASH_BUFFER,
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
                "qty": 0.0 if float(s["qty"]) <= DUST_THRESHOLD else float(s["qty"]),
                "heldQty": 0.0 if float(s["qty"]) <= DUST_THRESHOLD else float(s["qty"]),
                "proposedQty": proposed_buy_qty(s),
                "proposedNotional": confidence_notional(s),
                "qtyMeaning": "heldQty; proposedQty is the estimated new order size",
                "score": float(s["score"]),
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
            f"HOLD AI | enabled={HOLD_AI_ENABLED} | min_trades={HOLD_AI_MIN_TRADES} | min_hold={HOLD_AI_MIN_HOLD_MINUTES}m | good_hold={HOLD_AI_GOOD_SYMBOL_HOLD_MINUTES}m | max_positions={MAX_POSITIONS}",
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



# ============================================================
# STRATEGY STRICTNESS / LIVE GATE SETTINGS
# ============================================================

STRATEGY_SETTINGS_FILE = os.path.join("backend", "state", "strategy_settings.json")

STRATEGY_PRESETS = {
    "safe": {
        "label": "Safe",
        "aPlusMinConfidence": 0.70,
        "sniperMinConfidence": 0.58,
        "aPlusMinQuality": 0.026,
        "sniperMinQuality": 0.020,
    },
    "balanced": {
        "label": "Balanced",
        "aPlusMinConfidence": 0.62,
        "sniperMinConfidence": 0.54,
        "aPlusMinQuality": 0.022,
        "sniperMinQuality": 0.017,
    },
    "aggressive": {
        "label": "Aggressive",
        "aPlusMinConfidence": 0.55,
        "sniperMinConfidence": 0.50,
        "aPlusMinQuality": 0.018,
        "sniperMinQuality": 0.014,
    },
}

def _strategy_preset_from_level(level: int) -> str:
    try:
        level = int(level)
    except Exception:
        level = 1
    if level <= 0:
        return "safe"
    if level >= 2:
        return "aggressive"
    return "balanced"


def _save_strategy_settings(payload: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(STRATEGY_SETTINGS_FILE), exist_ok=True)
        with open(STRATEGY_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"STRATEGY SETTINGS SAVE ERROR: {e}")


def _load_strategy_settings() -> Dict[str, Any]:
    try:
        if os.path.exists(STRATEGY_SETTINGS_FILE):
            with open(STRATEGY_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"STRATEGY SETTINGS LOAD ERROR: {e}")
    return {"level": 0, "preset": "safe"}


def apply_strategy_settings(level: int = None, preset: str = None, save: bool = True) -> Dict[str, Any]:
    global A_PLUS_MIN_CONFIDENCE, SNIPER_MIN_CONFIDENCE, A_PLUS_MIN_QUALITY, SNIPER_MIN_QUALITY

    if preset:
        preset_key = str(preset).lower().strip()
    else:
        preset_key = _strategy_preset_from_level(0 if level is None else int(level))

    if preset_key not in STRATEGY_PRESETS:
        preset_key = "safe"

    if level is None:
        level = {"safe": 0, "balanced": 1, "aggressive": 2}.get(preset_key, 0)

    cfg = STRATEGY_PRESETS[preset_key]

    A_PLUS_MIN_CONFIDENCE = float(cfg["aPlusMinConfidence"])
    SNIPER_MIN_CONFIDENCE = float(cfg["sniperMinConfidence"])
    A_PLUS_MIN_QUALITY = float(cfg["aPlusMinQuality"])
    SNIPER_MIN_QUALITY = float(cfg["sniperMinQuality"])

    payload = {
        "ok": True,
        "level": int(level),
        "preset": preset_key,
        "label": cfg["label"],
        "aPlusMinConfidence": A_PLUS_MIN_CONFIDENCE,
        "sniperMinConfidence": SNIPER_MIN_CONFIDENCE,
        "aPlusMinQuality": A_PLUS_MIN_QUALITY,
        "sniperMinQuality": SNIPER_MIN_QUALITY,
        "updatedAt": datetime.now(UTC).isoformat(),
        "presets": STRATEGY_PRESETS,
    }

    if save:
        _save_strategy_settings(payload)

    try:
        latest_status["strategySettings"] = payload
        latest_status["aPlusMinConfidence"] = A_PLUS_MIN_CONFIDENCE
        latest_status["aPlusMinQuality"] = A_PLUS_MIN_QUALITY
        latest_status["config"]["sniperMinConfidence"] = SNIPER_MIN_CONFIDENCE
        latest_status["config"]["sniperMinQuality"] = SNIPER_MIN_QUALITY
        latest_status["lastAction"] = f"Trading strictness set to {cfg['label']}"
        latest_status["lastActionAt"] = payload["updatedAt"]
    except Exception:
        pass

    return payload


def apply_custom_a_plus_thresholds(confidence: float, quality: float, reason: str = "adaptive optimiser", save: bool = True) -> Dict[str, Any]:
    global A_PLUS_MIN_CONFIDENCE, A_PLUS_MIN_QUALITY
    confidence = max(0.50, min(0.90, float(confidence)))
    quality = max(0.010, min(0.100, float(quality)))
    previous_conf = float(A_PLUS_MIN_CONFIDENCE)
    previous_quality = float(A_PLUS_MIN_QUALITY)
    A_PLUS_MIN_CONFIDENCE = confidence
    A_PLUS_MIN_QUALITY = quality
    payload = current_strategy_settings_payload()
    payload.update({
        "preset": "custom", "label": "Adaptive Custom",
        "aPlusMinConfidence": confidence, "aPlusMinQuality": quality,
        "updatedAt": datetime.now(UTC).isoformat(), "changeReason": reason,
    })
    if save:
        _save_strategy_settings(payload)
    try:
        init_db()
        conn = db_connect()
        count = conn.execute("SELECT COUNT(*) FROM v2_strategy_versions").fetchone()[0]
        conn.execute(
            """INSERT INTO v2_strategy_versions
               (created_at, version_label, action, confidence, quality, previous_confidence, previous_quality, reason, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(UTC).isoformat(), f"V2.{count+1}", "APPLY", confidence, quality,
             previous_conf, previous_quality, reason, json.dumps({})),
        )
        conn.commit(); conn.close()
    except Exception as e:
        print(f"STRATEGY VERSION SAVE ERROR: {e}")
    return payload


def current_strategy_settings_payload() -> Dict[str, Any]:
    saved = _load_strategy_settings()
    preset_key = str(saved.get("preset") or _strategy_preset_from_level(int(saved.get("level", 0)))).lower()
    is_custom = preset_key == "custom"
    if preset_key not in STRATEGY_PRESETS and not is_custom:
        preset_key = "safe"
    preset_cfg = STRATEGY_PRESETS.get(preset_key, {"label": "Adaptive Custom"})

    # Keep runtime values as source of truth after startup has applied saved config.
    return {
        "ok": True,
        "level": int(saved.get("level", {"safe": 0, "balanced": 1, "aggressive": 2}.get(preset_key, -1))),
        "preset": preset_key,
        "label": preset_cfg["label"],
        "aPlusMinConfidence": float(A_PLUS_MIN_CONFIDENCE),
        "sniperMinConfidence": float(SNIPER_MIN_CONFIDENCE),
        "aPlusMinQuality": float(A_PLUS_MIN_QUALITY),
        "sniperMinQuality": float(SNIPER_MIN_QUALITY),
        "updatedAt": saved.get("updatedAt", ""),
        "presets": STRATEGY_PRESETS,
    }


@app.get("/strategy-settings")
def api_get_strategy_settings():
    return current_strategy_settings_payload()


@app.post("/strategy-settings")
def api_set_strategy_settings(request: Request, payload: dict = Body(...)):
    verify_api_key(request)
    level = payload.get("level")
    preset = payload.get("preset")
    result = apply_strategy_settings(level=level, preset=preset, save=True)
    return {**result, "message": f"Trading strictness set to {result['label']}"}


try:
    saved_strategy = _load_strategy_settings()
    if str(saved_strategy.get("preset") or "").lower() == "custom":
        apply_custom_a_plus_thresholds(
            float(saved_strategy.get("aPlusMinConfidence", A_PLUS_MIN_CONFIDENCE)),
            float(saved_strategy.get("aPlusMinQuality", A_PLUS_MIN_QUALITY)),
            reason="restore saved adaptive settings", save=False,
        )
    else:
        apply_strategy_settings(
            level=int(saved_strategy.get("level", 0)),
            preset=saved_strategy.get("preset", "safe"),
            save=False,
        )
except Exception as e:
    print(f"STRATEGY SETTINGS STARTUP APPLY ERROR: {e}")



# ============================================================
# LIVE POSITION LIMIT SETTINGS
# ============================================================

POSITION_SETTINGS_FILE = os.path.join("backend", "state", "position_settings.json")

def _save_position_settings(payload: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(POSITION_SETTINGS_FILE), exist_ok=True)
        with open(POSITION_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"POSITION SETTINGS SAVE ERROR: {e}")


def _load_position_settings() -> Dict[str, Any]:
    try:
        if os.path.exists(POSITION_SETTINGS_FILE):
            with open(POSITION_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        print(f"POSITION SETTINGS LOAD ERROR: {e}")
    return {"maxPositions": int(MAX_POSITIONS), "swingSafeMode": bool(globals().get("SWING_SNIPER_SAFE_MODE", False))}


def apply_position_settings(max_positions: int = None, save: bool = True) -> Dict[str, Any]:
    global MAX_POSITIONS, STRICT_MAX_POSITIONS

    try:
        value = int(max_positions if max_positions is not None else MAX_POSITIONS)
    except Exception:
        value = int(MAX_POSITIONS)

    value = max(1, min(10, value))
    if globals().get("SWING_SNIPER_SAFE_MODE", False):
        value = 1

    MAX_POSITIONS = value

    try:
        STRICT_MAX_POSITIONS = value
    except Exception:
        pass

    payload = {
        "ok": True,
        "maxPositions": int(MAX_POSITIONS),
        "min": 1,
        "max": 10,
        "updatedAt": datetime.now(UTC).isoformat(),
    }

    if save:
        _save_position_settings(payload)

    try:
        latest_status["positionSettings"] = payload
        latest_status["maxPositions"] = int(MAX_POSITIONS)
        latest_status["allowedNewPositions"] = allowed_new_position_count()
        latest_status["config"]["maxPositions"] = int(MAX_POSITIONS)
        latest_status["lastAction"] = f"Max positions set to {MAX_POSITIONS}"
        latest_status["lastActionAt"] = payload["updatedAt"]
    except Exception:
        pass

    return payload


def current_position_settings_payload() -> Dict[str, Any]:
    saved = _load_position_settings()
    return {
        "ok": True,
        "maxPositions": int(MAX_POSITIONS),
        "savedMaxPositions": int(saved.get("maxPositions", MAX_POSITIONS)),
        "min": 1,
        "max": 10,
        "updatedAt": saved.get("updatedAt", ""),
    }


@app.get("/position-settings")
def api_get_position_settings():
    return current_position_settings_payload()


@app.post("/position-settings")
def api_set_position_settings(request: Request, payload: dict = Body(...)):
    verify_api_key(request)
    result = apply_position_settings(max_positions=payload.get("maxPositions"), save=True)
    return {**result, "message": f"Max positions set to {result['maxPositions']}"}


try:
    saved_positions = _load_position_settings()
    apply_position_settings(max_positions=int(saved_positions.get("maxPositions", MAX_POSITIONS)), save=False)
except Exception as e:
    print(f"POSITION SETTINGS STARTUP APPLY ERROR: {e}")


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



@app.get("/v2/status")
def v2_status():
    return {
        "ok": True, "enabled": TRADEBOT_V2_ENABLED, "paper": PAPER,
        "liveBuyingEnabled": TRADEBOT_V2_LIVE_ENABLED,
        "mode": "paper" if PAPER else ("live" if TRADEBOT_V2_LIVE_ENABLED else "validation-only"),
        "features": {
            "decisionExplanation": True, "shadowVsOriginal": True,
            "adaptiveThresholdAdvisory": True, "autoApplyThresholds": V2_AUTO_APPLY_THRESHOLDS,
            "guardedOptimizer": True, "strategyTimeline": True,
            "marketDna": V4_MARKET_DNA_ENABLED, "similarityEngine": True,
            "patternMiner": True, "weeklyIntelligence": True
        },
        "rules": {
            "minSamples": V2_MIN_SYMBOL_SAMPLES, "minWinRate": V2_MIN_WIN_RATE,
            "minProfitFactor": V2_MIN_PROFIT_FACTOR, "minExpectancyPct": V2_MIN_EXPECTANCY_PCT,
            "lookbackDays": V2_LOOKBACK_DAYS, "maxPositions": MAX_POSITIONS,
            "logDecisions": V2_LOG_DECISIONS, "decisionDedupeSeconds": V2_DECISION_DEDUPE_SECONDS,
        },
    }

@app.get("/v2/explain/{symbol}")
def v2_explain(symbol: str):
    return v2_decision_explanation(symbol)

@app.get("/v2/decision-review")
def api_v2_decision_review(limit: int = 100):
    return v2_decision_review(limit)

@app.get("/v2/adaptive-thresholds")
def api_v2_adaptive_thresholds(horizon_hours: int = 24, min_samples: int = 25):
    return v2_adaptive_threshold_recommendations(horizon_hours, min_samples)

@app.get("/v2/strategy-timeline")
def api_v2_strategy_timeline(limit: int = 50):
    return v2_strategy_timeline(limit)

@app.post("/v2/strategy-rollback")
def api_v2_strategy_rollback(request: Request):
    verify_api_key(request)
    return v2_rollback_latest_strategy()

@app.get("/v4/status")
def api_v4_status():
    return v4_status_payload()

@app.get("/v4/market-dna")
def api_v4_market_dna(symbol: Optional[str] = None, limit: int = 100):
    return {"ok": True, "rows": v4_market_dna_rows(symbol, limit)}

@app.get("/v4/similarity/{symbol}")
def api_v4_similarity(symbol: str, horizon_hours: int = 24, limit: int = 50):
    return v4_similarity_for_symbol(symbol, horizon_hours, limit)

@app.get("/v4/explain/{decision_id}")
def api_v4_explain(decision_id: int, horizon_hours: int = 24, limit: int = 50):
    return v4_explain_decision(decision_id, horizon_hours, limit)

@app.get("/v4/explain-symbol/{symbol}")
def api_v4_explain_symbol(symbol: str, horizon_hours: int = 24, limit: int = 50):
    return v4_explain_latest_symbol(symbol, horizon_hours, limit)

@app.get("/v4/confidence/{symbol}")
def api_v4_confidence(symbol: str, horizon_hours: int = 24, limit: int = 50):
    return v4_contextual_confidence_for_symbol(symbol, horizon_hours, limit)

@app.get("/v4/confidence-decision/{decision_id}")
def api_v4_confidence_decision(decision_id: int, horizon_hours: int = 24, limit: int = 50):
    return v4_contextual_confidence_for_decision(decision_id, horizon_hours, limit)

@app.get("/v4/patterns")
def api_v4_patterns(horizon_hours: int = 24, min_samples: int = 8):
    return v4_pattern_report(horizon_hours, min_samples)

@app.get("/v4/weekly-intelligence")
def api_v4_weekly_intelligence(horizon_hours: int = 24):
    return v4_weekly_intelligence(horizon_hours)



# =========================
# TRADEBOT V4.3 — CONTEXTUAL SIMILARITY / CONFIDENCE INTELLIGENCE
# =========================
def _v4_session_name(dt: datetime) -> str:
    hour = dt.hour
    if hour < 14:
        return "PRE_MARKET_OR_EARLY_UTC"
    if hour < 17:
        return "US_MORNING"
    if hour < 20:
        return "US_AFTERNOON"
    return "US_LATE_OR_AFTER_HOURS"


def _v4_index_move(symbol: str) -> Optional[float]:
    try:
        st = state.get(symbol) or {}
        curve = st.get("price_curve") or []
        if len(curve) >= 2:
            first = float(curve[0].get("value") or 0.0)
            last = float(curve[-1].get("value") or 0.0)
            if first > 0:
                return (last / first) - 1.0
    except Exception:
        pass
    return None


def _v4_market_regime() -> str:
    spy = _v4_index_move("SPY")
    qqq = _v4_index_move("QQQ")
    values = [x for x in (spy, qqq) if x is not None]
    if not values:
        return "UNKNOWN"
    avg = sum(values) / len(values)
    if avg >= 0.007:
        return "STRONG_RISK_ON"
    if avg >= 0.0015:
        return "RISK_ON"
    if avg <= -0.007:
        return "STRONG_RISK_OFF"
    if avg <= -0.0015:
        return "RISK_OFF"
    return "SIDEWAYS"


def record_v4_market_dna(conn, decision_id: int, scan: Dict[str, Any], decision: str,
                         stage: str, reason: str, observed_at: datetime) -> None:
    """Persist the exact context available to the live bot. It never changes an order decision."""
    try:
        position_count = 0
        try:
            position_count = len(get_all_positions())
        except Exception:
            pass
        payload = {
            "confidenceLabel": scan.get("confidence_label"),
            "sniperReason": scan.get("sniper_reason"),
            "aPlusReason": scan.get("a_plus_reason"),
            "lockedToday": bool(scan.get("locked_today")),
            "custom": bool(scan.get("custom")),
            "source": "live_scan_context",
        }
        conn.execute(
            """INSERT OR REPLACE INTO v4_market_dna (
               decision_id,observed_at,symbol,decision,stage,reason,market_regime,
               session_name,weekday,hour_utc,price,confidence,quality,momentum,pullback,
               spread,ready_to_buy,sniper_pass,a_plus_pass,spy_move,qqq_move,
               position_count,payload_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                int(decision_id), observed_at.isoformat(), str(scan.get("symbol") or "").upper(),
                str(decision), str(stage), str(reason)[:1000], _v4_market_regime(),
                _v4_session_name(observed_at), int(observed_at.weekday()), int(observed_at.hour),
                float(scan.get("price") or 0.0), float(scan.get("confidence") or 0.0),
                float(scan.get("quality_score") or 0.0), float(scan.get("short_momentum") or 0.0),
                float(scan.get("pullback") or 0.0), float(scan.get("spread") or 0.0),
                int(bool(scan.get("ready_to_buy"))), int(bool(scan.get("sniper_pass"))),
                int(bool(scan.get("a_plus_pass"))), _v4_index_move("SPY"), _v4_index_move("QQQ"),
                position_count, json.dumps(payload, default=str),
            ),
        )
    except Exception as e:
        print(f"V4 MARKET DNA ERROR: {e}")


def v4_market_dna_rows(symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
    if not SQLITE_ENABLED:
        return []
    try:
        init_db(); conn = db_connect()
        params: List[Any] = []
        where = ""
        if symbol:
            where = "WHERE symbol=?"
            params.append(str(symbol).upper())
        params.append(max(1, min(int(limit), 2000)))
        rows = conn.execute(f"SELECT * FROM v4_market_dna {where} ORDER BY id DESC LIMIT ?", params).fetchall()
        conn.close()
        result = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json") or "{}")
            except Exception:
                item["payload"] = {}
            result.append(item)
        return result
    except Exception as e:
        print(f"V4 DNA READ ERROR: {e}")
        return []


def _v4_current_scan(symbol: str) -> Dict[str, Any]:
    sym = str(symbol or "").upper()
    for scan in latest_scans:
        if str(scan.get("symbol") or "").upper() == sym:
            return scan
    for scan in latest_status.get("scans") or []:
        if str(scan.get("symbol") or "").upper() == sym:
            return {
                "symbol": sym, "price": scan.get("price"), "confidence": scan.get("confidence"),
                "quality_score": scan.get("qualityScore"), "short_momentum": scan.get("shortMomentum"),
                "pullback": scan.get("pullback"), "spread": scan.get("spread"),
            }
    return {}


def _v4_weighted_similarity_summary(ranked: List[Dict[str, Any]], limit: int) -> Dict[str, Any]:
    """Summarise contextual neighbours with similarity, recency and sample-size controls."""
    chosen = ranked[:max(1, min(int(limit or V4_SIMILARITY_LIMIT), 200))]
    if not chosen:
        return {
            "matches": 0, "effectiveSamples": 0.0, "winRate": 0.0,
            "profitFactor": 0.0, "profitFactorDisplay": 0.0,
            "expectancyPct": 0.0, "averageSimilarity": 0.0,
            "evidenceReliability": 0.0, "recommendation": "WATCH",
        }

    weighted_wins = weighted_losses = weighted_return = total_weight = 0.0
    gross_profit = gross_loss = 0.0
    now = datetime.now(UTC)
    for item in chosen:
        similarity = max(0.0, min(1.0, float(item.get("similarity") or 0.0)))
        evaluated_at = item.get("evaluated_at") or item.get("observed_at")
        age_days = 365.0
        try:
            dt = datetime.fromisoformat(str(evaluated_at).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            age_days = max(0.0, (now - dt.astimezone(UTC)).total_seconds() / 86400.0)
        except Exception:
            pass
        recency = 0.5 ** (age_days / 90.0)  # 90-day half-life
        weight = max(0.01, similarity ** 2 * recency)
        ret = float(item.get("net_return_pct") or 0.0)
        total_weight += weight
        weighted_return += ret * weight
        if ret > 0:
            weighted_wins += weight
            gross_profit += ret * weight
        elif ret < 0:
            weighted_losses += weight
            gross_loss += abs(ret) * weight

    decisive_weight = weighted_wins + weighted_losses
    win_rate = weighted_wins / decisive_weight if decisive_weight > 0 else 0.0
    expectancy = weighted_return / total_weight if total_weight > 0 else 0.0
    pf = gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
    avg_similarity = sum(float(x.get("similarity") or 0.0) for x in chosen) / len(chosen)
    effective_samples = total_weight
    sample_score = min(1.0, effective_samples / max(1.0, float(V4_SIMILARITY_MIN_SAMPLES)))
    similarity_score = min(1.0, max(0.0, (avg_similarity - 0.25) / 0.50))
    reliability = sample_score * similarity_score
    enough = len(chosen) >= V4_SIMILARITY_MIN_SAMPLES and effective_samples >= max(4.0, V4_SIMILARITY_MIN_SAMPLES * 0.40)
    recommendation = "WATCH"
    if enough and reliability >= 0.35:
        if expectancy > 0.10 and pf >= 1.10 and win_rate >= 0.50:
            recommendation = "APPROVE"
        elif expectancy < 0 or pf < 0.90:
            recommendation = "BLOCK"
    return {
        "matches": len(chosen),
        "effectiveSamples": effective_samples,
        "winRate": win_rate,
        "profitFactor": pf,
        "profitFactorDisplay": min(pf, 20.0),
        "expectancyPct": expectancy,
        "averageSimilarity": avg_similarity,
        "evidenceReliability": reliability,
        "recommendation": recommendation,
        "chosen": chosen,
    }


def _v4_rank_contextual_rows(rows: List[Any], target: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Rank historical observations by the full setup, not merely by ticker."""
    numeric_scales = {
        "confidence": 0.15, "quality": 0.015, "momentum": 0.02,
        "pullback": 0.02, "spread": 0.01, "spy_move": 0.012, "qqq_move": 0.015,
    }
    ranked: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        distance = 0.0
        used = 0
        for key, scale in numeric_scales.items():
            tv = target.get(key)
            rv = item.get(key)
            if tv is None or rv is None:
                continue
            distance += ((float(rv or 0.0) - float(tv or 0.0)) / scale) ** 2
            used += 1
        if used == 0:
            continue
        if str(item.get("market_regime") or "UNKNOWN") != str(target.get("market_regime") or "UNKNOWN"):
            distance += 1.00
        if str(item.get("session_name") or "UNKNOWN") != str(target.get("session_name") or "UNKNOWN"):
            distance += 0.35
        if int(item.get("weekday") or -1) != int(target.get("weekday") or -2):
            distance += 0.08
        # Same-symbol history is useful but cannot dominate contextual evidence.
        if str(item.get("symbol") or "").upper() == str(target.get("symbol") or "").upper():
            distance = max(0.0, distance - 0.20)
        similarity = 1.0 / (1.0 + math.sqrt(max(0.0, distance)))
        ranked.append({**item, "similarity": similarity})
    ranked.sort(key=lambda x: x["similarity"], reverse=True)
    return ranked


def _v4_target_from_scan(symbol: str, current: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "symbol": str(symbol or "").upper(),
        "confidence": float(current.get("confidence") or 0.0),
        "quality": float(current.get("quality_score") or current.get("qualityScore") or 0.0),
        "momentum": float(current.get("short_momentum") or current.get("shortMomentum") or 0.0),
        "pullback": float(current.get("pullback") or 0.0),
        "spread": float(current.get("spread") or 0.0),
        "spy_move": _v4_index_move("SPY"), "qqq_move": _v4_index_move("QQQ"),
        "market_regime": _v4_market_regime(), "session_name": _v4_session_name(now),
        "weekday": now.weekday(),
    }


def v4_similarity_for_symbol(symbol: str, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    """V4.3 contextual nearest-neighbour evidence. Advisory only."""
    sym = str(symbol or "").upper().strip()
    current = _v4_current_scan(sym)
    base = {"ok": True, "version": "V4.3", "advisoryOnly": True, "symbol": sym, "horizonHours": int(horizon_hours)}
    if not current:
        return {**base, "recommendation": "WATCH", "reason": "No current scan available", "matches": 0}
    try:
        init_db(); conn = db_connect()
        rows = conn.execute(
            """SELECT d.*,o.net_return_pct,o.evaluated_at
               FROM v4_market_dna d JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL AND o.horizon_hours=?
               ORDER BY o.evaluated_at DESC LIMIT 5000""", (int(horizon_hours),)
        ).fetchall(); conn.close()
        target = _v4_target_from_scan(sym, current)
        ranked = _v4_rank_contextual_rows(list(rows), target)
        summary = _v4_weighted_similarity_summary(ranked, limit)
        chosen = summary.pop("chosen", [])
        return {**base, **summary, "minimumSamples": V4_SIMILARITY_MIN_SAMPLES,
                "currentFeatures": target,
                "topMatches": [{k: x.get(k) for k in (
                    "decision_id","symbol","observed_at","decision","stage","market_regime","session_name",
                    "confidence","quality","momentum","pullback","spread","spy_move","qqq_move",
                    "net_return_pct","similarity") } for x in chosen[:10]],
                "note": "Contextual evidence uses similarity and recency weighting and cannot place or block an order."}
    except Exception as e:
        return {**base, "ok": False, "error": str(e), "recommendation": "WATCH", "matches": 0}


def _v4_similarity_for_dna(dna: Dict[str, Any], horizon_hours: int = 24,
                           limit: int = 50, exclude_decision_id: Optional[int] = None) -> Dict[str, Any]:
    symbol = str(dna.get("symbol") or "").upper().strip()
    base = {"ok": True, "version": "V4.3", "advisoryOnly": True, "symbol": symbol, "horizonHours": int(horizon_hours)}
    try:
        init_db(); conn = db_connect()
        sql = """SELECT d.*,o.net_return_pct,o.evaluated_at FROM v4_market_dna d
                 JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
                 WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL AND o.horizon_hours=?"""
        params: List[Any] = [int(horizon_hours)]
        if exclude_decision_id is not None:
            sql += " AND d.decision_id<>?"; params.append(int(exclude_decision_id))
        sql += " ORDER BY o.evaluated_at DESC LIMIT 5000"
        rows = conn.execute(sql, params).fetchall(); conn.close()
        target = {k: dna.get(k) for k in (
            "symbol","confidence","quality","momentum","pullback","spread","spy_move","qqq_move",
            "market_regime","session_name","weekday")}
        ranked = _v4_rank_contextual_rows(list(rows), target)
        summary = _v4_weighted_similarity_summary(ranked, limit)
        chosen = summary.pop("chosen", [])
        return {**base, **summary, "minimumSamples": V4_SIMILARITY_MIN_SAMPLES,
                "currentFeatures": target,
                "topMatches": [{k: x.get(k) for k in (
                    "decision_id","symbol","observed_at","decision","stage","market_regime","session_name",
                    "confidence","quality","momentum","pullback","spread","spy_move","qqq_move",
                    "net_return_pct","similarity") } for x in chosen[:10]],
                "note": "Historical similarity is advisory and cannot place or block an order."}
    except Exception as e:
        return {**base, "ok": False, "error": str(e), "recommendation": "WATCH", "matches": 0}


def _v4_contextual_confidence(dna: Dict[str, Any], similarity: Dict[str, Any]) -> Dict[str, Any]:
    confidence = max(0.0, min(1.0, float(dna.get("confidence") or 0.0)))
    quality = max(0.0, float(dna.get("quality") or 0.0))
    momentum = float(dna.get("momentum") or 0.0)
    spread = max(0.0, float(dna.get("spread") or 0.0))
    technical = 100.0 * max(0.0, min(1.0,
        confidence * 0.55 + min(1.0, quality / 0.04) * 0.25 +
        max(0.0, min(1.0, 0.5 + momentum / 0.04)) * 0.15 +
        max(0.0, min(1.0, 1.0 - spread / 0.02)) * 0.05))
    recommendation = str(similarity.get("recommendation") or "WATCH")
    wr = float(similarity.get("winRate") or 0.0)
    expectancy = float(similarity.get("expectancyPct") or 0.0)
    historical_raw = wr * 70.0 + max(0.0, min(30.0, 15.0 + expectancy * 10.0))
    reliability = max(0.0, min(1.0, float(similarity.get("evidenceReliability") or 0.0)))
    historical = 50.0 + (historical_raw - 50.0) * reliability
    spy = dna.get("spy_move"); qqq = dna.get("qqq_move")
    moves = [float(x) for x in (spy, qqq) if x is not None]
    market = 50.0 if not moves else max(0.0, min(100.0, 50.0 + (sum(moves)/len(moves)) * 2500.0))
    if recommendation == "BLOCK": historical = min(historical, 40.0)
    elif recommendation == "APPROVE": historical = max(historical, 60.0)
    overall = technical * 0.55 + historical * 0.30 + market * 0.15
    grade = "HIGH" if overall >= 75 and reliability >= 0.35 else ("MEDIUM" if overall >= 60 else "LOW")
    return {
        "technicalScore": round(technical, 2), "historicalScore": round(historical, 2),
        "marketScore": round(market, 2), "dataReliabilityScore": round(reliability * 100.0, 2),
        "overallScore": round(overall, 2), "grade": grade,
        "advisoryRecommendation": recommendation,
        "weights": {"technical": 0.55, "historical": 0.30, "market": 0.15},
    }


def v4_contextual_confidence_for_symbol(symbol: str, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    sym = str(symbol or "").upper().strip(); current = _v4_current_scan(sym)
    if not current:
        return {"ok": False, "version": "V4.3", "symbol": sym, "message": "No current scan available"}
    now = datetime.now(UTC)
    dna = _v4_target_from_scan(sym, current)
    dna.update({"price": current.get("price")})
    similarity = v4_similarity_for_symbol(sym, horizon_hours, limit)
    return {"ok": True, "version": "V4.3", "advisoryOnly": True, "symbol": sym,
            "observedAt": now.isoformat(), "confidenceBreakdown": _v4_contextual_confidence(dna, similarity),
            "historicalEvidence": similarity,
            "note": "The score is explanatory only and does not change the live gate."}


def v4_contextual_confidence_for_decision(decision_id: int, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    try:
        init_db(); conn = db_connect()
        row = conn.execute("SELECT * FROM v4_market_dna WHERE decision_id=?", (int(decision_id),)).fetchone(); conn.close()
        if not row:
            return {"ok": False, "decisionId": int(decision_id), "message": "Decision not found"}
        dna = dict(row); similarity = _v4_similarity_for_dna(dna, horizon_hours, limit, int(decision_id))
        return {"ok": True, "version": "V4.3", "advisoryOnly": True, "decisionId": int(decision_id),
                "symbol": dna.get("symbol"), "confidenceBreakdown": _v4_contextual_confidence(dna, similarity),
                "historicalEvidence": similarity,
                "note": "The score audits a stored decision and cannot alter live trading."}
    except Exception as e:
        return {"ok": False, "decisionId": int(decision_id), "error": str(e)}


def _v4_explanation_reasons(dna: Dict[str, Any], similarity: Dict[str, Any]) -> List[Dict[str, Any]]:
    reasons: List[Dict[str, Any]] = []

    def add(label: str, passed: Optional[bool], detail: str) -> None:
        status = "INFO" if passed is None else ("PASS" if passed else "CAUTION")
        reasons.append({"status": status, "label": label, "detail": detail})

    confidence = float(dna.get("confidence") or 0.0)
    quality = float(dna.get("quality") or 0.0)
    momentum = float(dna.get("momentum") or 0.0)
    spread = float(dna.get("spread") or 0.0)
    add("Confidence", confidence >= 0.70, f"Recorded confidence {confidence:.3f}")
    add("Quality", quality >= 0.026, f"Recorded quality {quality:.4f}")
    add("Momentum", momentum > 0, f"Short momentum {momentum:.4f}")
    add("Spread", spread <= 0.01 if spread > 0 else None, f"Recorded spread {spread:.4f}")
    add("A+ gate", bool(dna.get("a_plus_pass")), "Passed" if dna.get("a_plus_pass") else "Not passed")
    add("Sniper gate", bool(dna.get("sniper_pass")), "Passed" if dna.get("sniper_pass") else "Not passed")
    add("Market regime", None, str(dna.get("market_regime") or "UNKNOWN"))
    add("Session", None, str(dna.get("session_name") or "UNKNOWN"))

    matches = int(similarity.get("matches") or 0)
    if matches:
        wr = float(similarity.get("winRate") or 0.0)
        pf = float(similarity.get("profitFactor") or 0.0)
        exp = float(similarity.get("expectancyPct") or 0.0)
        add("Historical evidence", similarity.get("recommendation") == "APPROVE",
            f"{matches} matches | win rate {wr:.1%} | PF {pf:.2f} | expectancy {exp:.3f}%")
    else:
        add("Historical evidence", None, "No completed comparable outcomes yet")
    return reasons


def v4_explain_decision(decision_id: int, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    """Return a complete, human-readable audit for one stored decision."""
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db()
        conn = db_connect()
        row = conn.execute(
            """SELECT d.*,s.timestamp AS decision_timestamp,s.payload_json AS decision_payload_json
               FROM v4_market_dna d
               LEFT JOIN v2_setup_decisions s ON s.id=d.decision_id
               WHERE d.decision_id=?""",
            (int(decision_id),),
        ).fetchone()
        if not row:
            conn.close()
            return {"ok": False, "message": "Decision not found", "decisionId": int(decision_id)}
        dna = dict(row)
        outcomes = [dict(r) for r in conn.execute(
            """SELECT horizon_hours,status,due_at,evaluated_at,outcome_price,return_pct,
                      net_return_pct,estimated_cost_pct,error
               FROM v2_observation_outcomes WHERE decision_id=? ORDER BY horizon_hours""",
            (int(decision_id),),
        ).fetchall()]
        conn.close()
        try:
            dna["payload"] = json.loads(dna.pop("payload_json") or "{}")
        except Exception:
            dna["payload"] = {}
        try:
            dna["decisionPayload"] = json.loads(dna.pop("decision_payload_json") or "{}")
        except Exception:
            dna["decisionPayload"] = {}

        similarity = _v4_similarity_for_dna(dna, horizon_hours, limit, int(decision_id))
        confidence_breakdown = _v4_contextual_confidence(dna, similarity)
        reasons = _v4_explanation_reasons(dna, similarity)
        original_decision = str(dna.get("decision") or "UNKNOWN")
        advisory = str(similarity.get("recommendation") or "WATCH")
        agreement = (
            "AGREE" if (original_decision == "APPROVE" and advisory == "APPROVE") or
                       (original_decision != "APPROVE" and advisory == "BLOCK")
            else "INSUFFICIENT_EVIDENCE" if advisory == "WATCH" else "DISAGREE"
        )
        return {
            "ok": True,
            "version": "V4.3",
            "advisoryOnly": True,
            "decisionId": int(decision_id),
            "symbol": dna.get("symbol"),
            "decision": original_decision,
            "stage": dna.get("stage"),
            "reason": dna.get("reason"),
            "observedAt": dna.get("observed_at"),
            "marketRegime": dna.get("market_regime"),
            "session": dna.get("session_name"),
            "features": {k: dna.get(k) for k in (
                "price", "confidence", "quality", "momentum", "pullback", "spread",
                "ready_to_buy", "sniper_pass", "a_plus_pass", "spy_move", "qqq_move",
                "position_count"
            )},
            "historicalEvidence": similarity,
            "confidenceBreakdown": confidence_breakdown,
            "explanation": reasons,
            "advisoryAgreement": agreement,
            "outcomes": outcomes,
            "note": "This explanation audits the decision; it does not alter live trading.",
        }
    except Exception as e:
        return {"ok": False, "decisionId": int(decision_id), "error": str(e)}


def v4_explain_latest_symbol(symbol: str, horizon_hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    try:
        init_db()
        conn = db_connect()
        row = conn.execute(
            "SELECT decision_id FROM v4_market_dna WHERE symbol=? ORDER BY id DESC LIMIT 1",
            (sym,),
        ).fetchone()
        conn.close()
        if not row:
            return {"ok": False, "symbol": sym, "message": "No Market DNA decision found for symbol"}
        return v4_explain_decision(int(row["decision_id"]), horizon_hours, limit)
    except Exception as e:
        return {"ok": False, "symbol": sym, "error": str(e)}

def _v4_metrics(values: List[float]) -> Dict[str, Any]:
    wins = [x for x in values if x > 0]; losses = [x for x in values if x < 0]
    gp, gl = sum(wins), abs(sum(losses))
    return {"samples": len(values), "winRate": len(wins) / max(1, len(wins)+len(losses)),
            "profitFactor": gp / gl if gl > 0 else (99.0 if gp > 0 else 0.0),
            "expectancyPct": sum(values) / max(1, len(values)),
            "bestReturnPct": max(values) if values else 0.0, "worstReturnPct": min(values) if values else 0.0}


def v4_pattern_report(horizon_hours: int = 24, min_samples: int = 8) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db(); conn = db_connect()
        rows = [dict(r) for r in conn.execute(
            """SELECT d.*,o.net_return_pct FROM v4_market_dna d
               JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL AND o.horizon_hours=?""",
            (int(horizon_hours),)).fetchall()]
        conn.close()
        groups: Dict[str, Dict[str, List[float]]] = {
            "marketRegime": {}, "session": {}, "stage": {}, "confidenceBand": {}, "qualityBand": {}
        }
        for r in rows:
            ret = float(r.get("net_return_pct") or 0.0)
            conf = float(r.get("confidence") or 0.0); qual = float(r.get("quality") or 0.0)
            conf_band = f"{math.floor(conf*10)/10:.1f}-{math.floor(conf*10)/10+0.1:.1f}"
            qlow = math.floor(qual/0.005)*0.005
            qual_band = f"{qlow:.3f}-{qlow+0.005:.3f}"
            keys = {"marketRegime": str(r.get("market_regime") or "UNKNOWN"),
                    "session": str(r.get("session_name") or "UNKNOWN"),
                    "stage": str(r.get("stage") or "UNKNOWN"),
                    "confidenceBand": conf_band, "qualityBand": qual_band}
            for category, key in keys.items():
                groups[category].setdefault(key, []).append(ret)
        output = {}
        for category, mapping in groups.items():
            items = [{"name": name, **_v4_metrics(vals)} for name, vals in mapping.items() if len(vals) >= int(min_samples)]
            items.sort(key=lambda x: (x["expectancyPct"], x["profitFactor"], x["samples"]), reverse=True)
            output[category] = items
        all_metrics = _v4_metrics([float(r.get("net_return_pct") or 0.0) for r in rows])
        return {"ok": True, "advisoryOnly": True, "horizonHours": int(horizon_hours),
                "minimumSamplesPerPattern": int(min_samples), "observations": len(rows),
                "overall": all_metrics, "patterns": output,
                "bestPatterns": [{"category": cat, **items[0]} for cat, items in output.items() if items],
                "note": "Patterns are descriptive evidence only; no live threshold is changed."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def v4_weekly_intelligence(horizon_hours: int = 24) -> Dict[str, Any]:
    report = v4_pattern_report(horizon_hours, V4_PATTERN_MIN_SAMPLES)
    if not report.get("ok"):
        return report
    cutoff = datetime.now(UTC) - timedelta(days=7)
    try:
        init_db(); conn = db_connect()
        rows = [dict(r) for r in conn.execute(
            """SELECT d.*,o.net_return_pct FROM v4_market_dna d
               JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL
                 AND o.horizon_hours=? AND d.observed_at>=?""",
            (int(horizon_hours), cutoff.isoformat())).fetchall()]
        conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    metrics = _v4_metrics([float(r.get("net_return_pct") or 0.0) for r in rows])
    best = report.get("bestPatterns") or []
    recommendation = "COLLECT_MORE_EVIDENCE"
    if metrics["samples"] >= V4_PATTERN_MIN_SAMPLES:
        recommendation = "CONTINUE_CURRENT_GUARDS" if metrics["expectancyPct"] >= 0 else "REVIEW_WEAK_PATTERNS"
    return {"ok": True, "advisoryOnly": True, "periodDays": 7, "horizonHours": int(horizon_hours),
            "weekly": metrics, "recommendation": recommendation, "topPatterns": best[:5],
            "marketDnaRows": len(v4_market_dna_rows(limit=2000)),
            "nextStep": "Use similarity and pattern evidence in shadow mode before any guarded optimiser proposal."}


def v4_status_payload() -> Dict[str, Any]:
    try:
        rows = v4_market_dna_rows(limit=1)
        init_db(); conn = db_connect()
        count = int(conn.execute("SELECT COUNT(*) FROM v4_market_dna").fetchone()[0])
        complete = int(conn.execute("""SELECT COUNT(*) FROM v4_market_dna d JOIN v2_observation_outcomes o
                                      ON o.decision_id=d.decision_id WHERE o.status='COMPLETE'""").fetchone()[0])
        conn.close()
    except Exception:
        count, complete, rows = 0, 0, []
    return {"ok": True, "version": "V4.3", "mode": "advisory-contextual-intelligence",
            "marketDnaEnabled": V4_MARKET_DNA_ENABLED, "dnaRows": count,
            "completedOutcomeLinks": complete, "latestDna": rows[0] if rows else None,
            "features": {"marketDna": True, "similarityEngine": True, "patternMiner": True,
                         "weeklyIntelligence": True, "explainability": True, "contextualSimilarity": True,
                         "confidenceBreakdown": True, "recencyWeighting": True, "liveGateChanged": False}}


# =========================
# TRADEBOT V2 DECISION EXPLANATION + ADAPTIVE ADVISORY
# =========================
def _v2_metric_grade(samples: int, profit_factor: float, expectancy: float) -> str:
    if samples < 8:
        return "LOW"
    if samples >= 30 and profit_factor >= 1.50 and expectancy > 0:
        return "HIGH"
    if profit_factor >= 1.10 and expectancy >= 0:
        return "MEDIUM"
    return "LOW"


def _v2_drawdown(returns: List[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for value in returns:
        equity += float(value)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def _v2_candidate_metrics(observations: List[Dict[str, Any]], confidence: float, quality: float, min_samples: int) -> Optional[Dict[str, Any]]:
    selected = [r for r in observations if float(r.get("confidence") or 0) >= confidence and float(r.get("quality") or 0) >= quality]
    returns = [float(r.get("net_return_pct") or 0) for r in selected]
    if len(returns) < int(min_samples):
        return None
    wins = [x for x in returns if x > 0]
    losses = [x for x in returns if x < 0]
    gp, gl = sum(wins), abs(sum(losses))
    pf = gp / gl if gl > 0 else (99.0 if gp > 0 else 0.0)
    exp = sum(returns) / len(returns)
    wr = len(wins) / (len(wins)+len(losses)) if (wins or losses) else 0.0
    dd = _v2_drawdown(returns)
    robustness = min(1.0, len(returns)/100.0)
    score = exp * min(pf, 4.0) * (0.5 + 0.5*robustness) / (1.0 + dd)
    return {"confidence": confidence, "quality": quality, "samples": len(returns), "winRate": wr,
            "profitFactor": pf, "expectancyPct": exp, "maxDrawdownPct": dd,
            "largestLossPct": min(returns) if returns else 0.0, "score": score}


def _v2_blacklisted_symbols() -> set:
    blocked = set()
    try:
        stats = symbol_stats()
        rows = stats.values() if isinstance(stats, dict) else stats
        for row in rows or []:
            if str(row.get("trust") or "").upper() in {"BLACKLIST", "AVOID"}:
                blocked.add(str(row.get("symbol") or "").upper())
    except Exception:
        try:
            for row in (analytics_payload().get("worstStocks") or []):
                if str(row.get("trust") or "").upper() in {"BLACKLIST", "AVOID"}:
                    blocked.add(str(row.get("symbol") or "").upper())
        except Exception:
            pass
    return blocked


def _v2_step_toward(current: float, target: float, maximum_step: float, decimals: int) -> float:
    delta = max(-maximum_step, min(maximum_step, target-current))
    return round(current+delta, decimals)


def v2_adaptive_threshold_recommendations(horizon_hours: int = 24, min_samples: int = 25) -> Dict[str, Any]:
    """Guarded optimiser: blacklist filtering, rolling windows, drawdown, stability and optional staged apply."""
    current_conf, current_quality = float(A_PLUS_MIN_CONFIDENCE), float(A_PLUS_MIN_QUALITY)
    result = {"ok": True, "advisoryOnly": not V2_AUTO_APPLY_THRESHOLDS, "applied": False,
              "horizonHours": int(horizon_hours), "minimumSamples": int(min_samples),
              "current": {"confidence": current_conf, "quality": current_quality}}
    if not SQLITE_ENABLED:
        return {**result, "ok": False, "message": "SQLite disabled"}
    try:
        init_db(); conn=db_connect()
        blocked=_v2_blacklisted_symbols()
        rows=conn.execute("""WITH ranked AS (
              SELECT d.symbol,d.confidence,d.quality,o.net_return_pct,o.observed_at,
              ROW_NUMBER() OVER (PARTITION BY COALESCE(o.sample_key,CAST(o.decision_id AS TEXT)),o.horizon_hours ORDER BY o.id ASC) rn
              FROM v2_observation_outcomes o JOIN v2_setup_decisions d ON d.id=o.decision_id
              WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL AND o.horizon_hours=?)
              SELECT symbol,confidence,quality,net_return_pct,observed_at FROM ranked WHERE rn=1""",(int(horizon_hours),)).fetchall()
        all_obs=[dict(r) for r in rows]
        observations=[r for r in all_obs if str(r.get("symbol") or "").upper() not in blocked]
        now=datetime.now(UTC)
        windows=[24,72,168,720]
        confs=sorted(set([round(x,2) for x in [0.55,0.58,0.60,0.62,0.65,0.66,0.67,0.68,0.69,0.70,0.72,0.75,current_conf]]))
        quals=sorted(set([round(x,3) for x in [0.018,0.020,0.022,0.024,0.025,0.026,0.028,0.030,current_quality]]))
        candidates=[]
        for conf in confs:
            for qual in quals:
                window_metrics=[]
                for hours in windows:
                    cutoff=now-timedelta(hours=hours)
                    subset=[]
                    for r in observations:
                        try: dt=datetime.fromisoformat(str(r.get("observed_at")).replace("Z","+00:00"))
                        except Exception: continue
                        if dt>=cutoff: subset.append(r)
                    metric=_v2_candidate_metrics(subset,conf,qual,min_samples)
                    if metric: window_metrics.append({"hours":hours,**metric})
                base=_v2_candidate_metrics(observations,conf,qual,min_samples)
                if not base: continue
                positive=sum(1 for m in window_metrics if m["expectancyPct"]>0 and m["profitFactor"]>=1.1)
                base["positiveWindows"]=positive; base["availableWindows"]=len(window_metrics); base["windows"]=window_metrics
                base["stableScore"]=base["score"]*(0.5+0.5*(positive/max(1,len(window_metrics))))
                candidates.append(base)
        candidates.sort(key=lambda x:(x["stableScore"],x["samples"]),reverse=True)
        current=next((x for x in candidates if x["confidence"]==round(current_conf,2) and x["quality"]==round(current_quality,3)),None)
        best=candidates[0] if candidates else None
        recommendation="KEEP_CURRENT"; reason="Not enough completed, non-blacklisted evidence."
        eligible=False; staged=None
        if best and current:
            improvement=(best["stableScore"]-current["stableScore"])/max(abs(current["stableScore"]),1e-9)
            dd_ok=best["maxDrawdownPct"] <= current["maxDrawdownPct"]*(1+V2_OPTIMIZER_MAX_DRAWDOWN_INCREASE)+0.05
            windows_ok=best["positiveWindows"]>=max(1,(best["availableWindows"]+1)//2)
            materially_better=improvement>=V2_OPTIMIZER_MIN_IMPROVEMENT and best["expectancyPct"]>current["expectancyPct"] and best["profitFactor"]>=current["profitFactor"]
            eligible=bool(materially_better and dd_ok and windows_ok)
            if eligible:
                staged={**best,
                    "confidence":_v2_step_toward(current_conf,best["confidence"],V2_OPTIMIZER_MAX_CONF_STEP,2),
                    "quality":_v2_step_toward(current_quality,best["quality"],V2_OPTIMIZER_MAX_QUALITY_STEP,3),
                    "targetConfidence":best["confidence"],"targetQuality":best["quality"]}
                recommendation="STABILITY_TEST"; reason="Candidate passed blacklist, rolling-window and drawdown safeguards."
            else: reason="Best candidate did not pass every stability, improvement and drawdown safeguard."
        stable_key=f"{(staged or best or {}).get('confidence')}:{(staged or best or {}).get('quality')}"
        conn.execute("INSERT INTO v2_optimizer_evaluations (evaluated_at,horizon_hours,candidate_confidence,candidate_quality,current_confidence,current_quality,eligible,stable_key,payload_json) VALUES (?,?,?,?,?,?,?,?,?)",
            (now.isoformat(),int(horizon_hours),(staged or best or {}).get("confidence"),(staged or best or {}).get("quality"),current_conf,current_quality,1 if eligible else 0,stable_key,json.dumps({"best":best,"current":current})))
        recent=conn.execute("SELECT stable_key,eligible FROM v2_optimizer_evaluations ORDER BY id DESC LIMIT ?",(V2_OPTIMIZER_REQUIRED_STABLE_RUNS,)).fetchall()
        stable_runs=len(recent)==V2_OPTIMIZER_REQUIRED_STABLE_RUNS and all(int(r["eligible"])==1 and r["stable_key"]==stable_key for r in recent)
        if eligible and stable_runs: recommendation="READY_TO_APPLY"
        if eligible and stable_runs and V2_AUTO_APPLY_THRESHOLDS and staged:
            apply_custom_a_plus_thresholds(staged["confidence"],staged["quality"],"guarded adaptive optimiser",True)
            result["applied"]=True; recommendation="APPLIED_STAGED_CHANGE"
        conn.commit(); conn.close()
        result.update({"observations":len(observations),"excludedBlacklistSymbols":sorted(blocked),"excludedObservationCount":len(all_obs)-len(observations),
            "recommendation":recommendation,"reason":reason,"recommended":best,"stagedRecommendation":staged,"currentEvidence":current,
            "topCandidates":candidates[:10],"stability":{"requiredRuns":V2_OPTIMIZER_REQUIRED_STABLE_RUNS,"matchingRuns":sum(1 for r in recent if r["stable_key"]==stable_key and int(r["eligible"])==1),"passed":stable_runs},
            "safeguards":{"rollingWindowsHours":windows,"minimumImprovementPct":V2_OPTIMIZER_MIN_IMPROVEMENT*100,"maxDrawdownIncreasePct":V2_OPTIMIZER_MAX_DRAWDOWN_INCREASE*100,"maxConfidenceStep":V2_OPTIMIZER_MAX_CONF_STEP,"maxQualityStep":V2_OPTIMIZER_MAX_QUALITY_STEP},
            "safetyNote":"Thresholds only apply when auto-apply is enabled and all safeguards pass for consecutive evaluations."})
        return result
    except Exception as e:
        return {**result,"ok":False,"error":str(e)}


def v2_rollback_latest_strategy() -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    try:
        init_db(); conn = db_connect()
        row = conn.execute("SELECT * FROM v2_strategy_versions WHERE action='APPLY' ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            conn.close(); return {"ok": False, "message": "No applied adaptive strategy version to roll back"}
        row = dict(row)
        previous_conf = row.get("previous_confidence")
        previous_quality = row.get("previous_quality")
        if previous_conf is None or previous_quality is None:
            conn.close(); return {"ok": False, "message": "Previous thresholds are unavailable"}
        conn.close()
        result = apply_custom_a_plus_thresholds(float(previous_conf), float(previous_quality), f"rollback of strategy version {row.get('version_label')}", True)
        return {"ok": True, "rolledBack": row.get("version_label"), "settings": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def v2_strategy_timeline(limit: int = 50) -> Dict[str, Any]:
    if not SQLITE_ENABLED: return {"ok":False,"message":"SQLite disabled","rows":[]}
    try:
        init_db(); conn=db_connect()
        rows=[dict(r) for r in conn.execute("SELECT * FROM v2_strategy_versions ORDER BY id DESC LIMIT ?",(max(1,min(int(limit),200)),)).fetchall()]
        conn.close()
        for r in rows:
            try: r["metrics"]=json.loads(r.pop("metrics_json") or "{}")
            except Exception: r["metrics"]={}
        return {"ok":True,"count":len(rows),"rows":rows}
    except Exception as e: return {"ok":False,"error":str(e),"rows":[]}


def v2_decision_explanation(symbol: str) -> Dict[str, Any]:
    sym = str(symbol or "").upper().strip()
    scans = latest_status.get("scans") or []
    scan = next((s for s in scans if str(s.get("symbol", "")).upper() == sym), {})
    profile = v2_symbol_expectancy(sym)
    forward = profile.get("forwardShadow") or v2_forward_shadow_profile(sym)
    recent = [r for r in v2_recent_decisions(500) if str(r.get("symbol", "")).upper() == sym]
    latest = recent[0] if recent else {}
    confidence = float(scan.get("confidence") if scan else latest.get("confidence") or 0.0)
    quality = float(scan.get("qualityScore") if scan else latest.get("quality") or 0.0)
    momentum = float(scan.get("shortMomentum") if scan else latest.get("momentum") or 0.0)
    pullback = float(scan.get("pullback") if scan else latest.get("pullback") or 0.0)
    checks = [
        {"name": "Sniper confidence", "passed": confidence >= float(SNIPER_MIN_CONFIDENCE), "value": confidence, "required": float(SNIPER_MIN_CONFIDENCE)},
        {"name": "Sniper quality", "passed": quality >= float(SNIPER_MIN_QUALITY), "value": quality, "required": float(SNIPER_MIN_QUALITY)},
        {"name": "A+ confidence", "passed": confidence >= float(A_PLUS_MIN_CONFIDENCE), "value": confidence, "required": float(A_PLUS_MIN_CONFIDENCE)},
        {"name": "A+ quality", "passed": quality >= float(A_PLUS_MIN_QUALITY), "value": quality, "required": float(A_PLUS_MIN_QUALITY)},
        {"name": "Momentum non-negative", "passed": momentum >= 0.0, "value": momentum, "required": 0.0},
        {"name": "Historical expectancy gate", "passed": bool(profile.get("approved")), "value": float(profile.get("expectancyPct") or 0.0), "required": float(V2_MIN_EXPECTANCY_PCT)},
    ]
    live_decision = str(latest.get("decision") or ("APPROVED" if scan.get("aPlusPass") else "REJECTED" if scan else "UNKNOWN"))
    live_reason = str(latest.get("reason") or scan.get("aPlusReason") or scan.get("sniperReason") or "No recorded reason")
    shadow_decision = str(forward.get("recommendation") or "WATCH")
    mismatch = ((live_decision == "APPROVED" and shadow_decision == "BLOCK") or
                (live_decision == "REJECTED" and shadow_decision == "APPROVE"))
    estimated_skip_cost = None
    if live_decision == "REJECTED" and shadow_decision == "APPROVE":
        estimated_skip_cost = float(forward.get("expectancyPct") or 0.0)
    samples = int(forward.get("samples") or 0)
    pf = float(forward.get("profitFactor") or 0.0)
    exp = float(forward.get("expectancyPct") or 0.0)
    return {
        "ok": True,
        "symbol": sym,
        "decision": live_decision,
        "stage": latest.get("stage"),
        "reason": live_reason,
        "checks": checks,
        "historicalEvidence": profile,
        "forwardShadow": forward,
        "comparison": {
            "originalDecision": live_decision,
            "shadowRecommendation": shadow_decision,
            "disagreement": mismatch,
            "estimatedCostOfSkipPct": estimated_skip_cost,
            "evidenceConfidence": _v2_metric_grade(samples, pf, exp),
            "note": "Shadow advice is evidence-only and cannot place an order.",
        },
        "latestScan": scan,
        "recentDecisions": recent[:20],
    }


def v2_decision_review(limit: int = 100) -> Dict[str, Any]:
    decisions = v2_recent_decisions(max(1, min(int(limit), 500)))
    rows = []
    profile_cache: Dict[str, Dict[str, Any]] = {}
    for d in decisions:
        sym = str(d.get("symbol") or "").upper()
        if sym not in profile_cache:
            profile_cache[sym] = v2_forward_shadow_profile(sym)
        shadow = profile_cache[sym]
        original = str(d.get("decision") or "UNKNOWN")
        recommendation = str(shadow.get("recommendation") or "WATCH")
        disagreement = ((original == "APPROVED" and recommendation == "BLOCK") or
                        (original == "REJECTED" and recommendation == "APPROVE"))
        rows.append({
            "decisionId": d.get("id"), "timestamp": d.get("timestamp"), "symbol": sym,
            "originalDecision": original, "stage": d.get("stage"), "reason": d.get("reason"),
            "confidence": d.get("confidence"), "quality": d.get("quality"),
            "shadowRecommendation": recommendation,
            "shadowSamples": shadow.get("samples"), "shadowWinRate": shadow.get("winRate"),
            "shadowProfitFactor": shadow.get("profitFactor"), "shadowExpectancyPct": shadow.get("expectancyPct"),
            "disagreement": disagreement,
            "estimatedCostOfSkipPct": float(shadow.get("expectancyPct") or 0.0) if original == "REJECTED" and recommendation == "APPROVE" else None,
        })
    return {
        "ok": True, "advisoryOnly": True, "count": len(rows),
        "disagreements": sum(1 for r in rows if r["disagreement"]),
        "rows": rows,
        "note": "Comparison only; live ordering and saved thresholds remain unchanged.",
    }


@app.get("/v2/intelligence-summary")
def api_v2_intelligence_summary():
    return v2_intelligence_summary()

@app.get("/v2/setup-profiles")
def api_v2_setup_profiles(limit: int = 100):
    return {"ok": True, "profiles": v2_setup_profiles(limit)}

@app.get("/v2/recent-decisions")
def api_v2_recent_decisions(limit: int = 100):
    return {"ok": True, "decisions": v2_recent_decisions(limit)}

@app.get("/v2/outcomes-summary")
def api_v2_outcomes_summary(symbol: Optional[str] = None):
    return v2_outcomes_summary(symbol)

@app.get("/v2/replay")
def api_v2_replay(symbol: Optional[str] = None, limit: int = 200):
    return {"ok": True, "rows": v2_replay_rows(symbol, limit)}

@app.get("/v2/shadow-recommendations")
def api_v2_shadow_recommendations(symbol: Optional[str] = None):
    if symbol:
        return {"ok": True, "shadowMode": True, "recommendations": [v2_forward_shadow_profile(symbol)]}
    summary = v2_outcomes_summary()
    return {"ok": bool(summary.get("ok")), "shadowMode": True,
            "note": "Advisory only; live gate unchanged.",
            "recommendations": summary.get("shadowRecommendations", [])}

@app.post("/v2/evaluate-outcomes")
def api_v2_evaluate_outcomes(request: Request, limit: int = 100):
    verify_api_key(request)
    return v2_evaluate_due_outcomes(limit)

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
    seeded_outcomes = v2_seed_missing_outcomes()
    if seeded_outcomes:
        print(f"V2 OUTCOMES | seeded={seeded_outcomes}")
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

                try:
                    v2_evaluate_due_outcomes()
                except Exception as e:
                    print(f"V2 OUTCOME LOOP ERROR: {e}")

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
    global bot_thread_started, v6_sync_thread_started, v7_weekend_thread_started
    if not bot_thread_started:
        bot_thread_started = True
        threading.Thread(target=run_bot_loop, daemon=True).start()
    if V6_BRAINS_ENABLED and V6_AUTO_SYNC_ENABLED and not v6_sync_thread_started:
        v6_sync_thread_started = True
        threading.Thread(target=v6_auto_sync_worker, daemon=True).start()
    if V7_ENABLED and V7_WEEKEND_MAINTENANCE_ENABLED and not v7_weekend_thread_started:
        v7_weekend_thread_started = True
        threading.Thread(target=v7_weekend_worker, daemon=True).start()



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
    # Always read closed trades fresh from SQLite so Reports does not show stale April rows.
    closed = closed_trades_from_db(500) if "closed_trades_from_db" in globals() else (status.get("closedTrades") or [])
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
        "closedTrades": closed[:200] if isinstance(closed, list) else [],
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
STRICT_STOP_LOSS_PCT = float(os.getenv("STRICT_STOP_LOSS_PCT", "-4.00"))
STRICT_TAKE_PROFIT_PCT = float(os.getenv("STRICT_TAKE_PROFIT_PCT", "8.00"))
STRICT_TRAIL_START_PCT = float(os.getenv("STRICT_TRAIL_START_PCT", "6.00"))
STRICT_TRAIL_DROP_PCT = float(os.getenv("STRICT_TRAIL_DROP_PCT", "2.00"))
STRICT_MAX_POSITIONS = int(os.getenv("STRICT_MAX_POSITIONS", "1"))
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
        if "reconcile_auto_universe_rows" in globals():
            rows = reconcile_auto_universe_rows(rows, len(rows) or AUTO_UNIVERSE_SIZE)
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

# ============================================================
# FINAL COMPATIBILITY ROUTES: BASELINE + BUY SIZE MODE
# Append-only: do not remove existing working routes.
# ============================================================

_COMPAT_STATE_DIR = os.path.join("backend", "state")
_COMPAT_BASELINE_FILE = os.path.join(_COMPAT_STATE_DIR, "equity_baseline.json")
_COMPAT_BUY_SIZE_FILE = os.path.join(_COMPAT_STATE_DIR, "buy_size_mode.json")

def _compat_num(v, default=0.0):
    try:
        return float(v or default)
    except Exception:
        return float(default)

def _compat_read(path, default=None):
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"COMPAT READ ERROR {path}: {e}", flush=True)
    return dict(default or {})

def _compat_write(path, payload):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        payload = dict(payload)
        payload["savedAt"] = time.time()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
    except Exception as e:
        print(f"COMPAT WRITE ERROR {path}: {e}", flush=True)

def _compat_auth(request: Request = None):
    if request is not None and "verify_api_key" in globals():
        return verify_api_key(request)
    return True

def _compat_gbp(usd):
    try:
        return float(money_gbp(float(usd or 0)))
    except Exception:
        try:
            return float(usd or 0) * float(get_usd_to_gbp_rate())
        except Exception:
            return float(usd or 0) * 0.78

def _compat_account_equity():
    try:
        a = get_account()
        return float(getattr(a, "equity", 0) or 0), float(getattr(a, "buying_power", 0) or 0)
    except Exception:
        return 0.0, 0.0

def _compat_baseline_value():
    data = _compat_read(_COMPAT_BASELINE_FILE, {})
    return _compat_num(data.get("baseline"), 0.0)

@app.get("/baseline")
def compat_get_baseline():
    baseline = _compat_baseline_value()
    return {
        "ok": True,
        "baseline": baseline,
        "baselineGbp": round(_compat_gbp(baseline), 2),
        "source": "saved" if baseline > 0 else "none",
    }

@app.post("/set-baseline")
def compat_set_baseline(payload: dict = Body(...), request: Request = None):
    _compat_auth(request)
    value = _compat_num(payload.get("baseline") or payload.get("value") or payload.get("amount"), 0.0)
    if value <= 0:
        raise HTTPException(status_code=400, detail="Invalid baseline")
    _compat_write(_COMPAT_BASELINE_FILE, {"baseline": value})
    return {
        "ok": True,
        "message": f"Baseline saved at ${value:.2f}",
        "baseline": value,
        "baselineGbp": round(_compat_gbp(value), 2),
        "depositSource": "saved",
    }

@app.post("/reset-baseline")
def compat_reset_baseline(request: Request = None):
    _compat_auth(request)
    equity, _bp = _compat_account_equity()
    if equity <= 0:
        raise HTTPException(status_code=400, detail="Could not read current equity")
    _compat_write(_COMPAT_BASELINE_FILE, {"baseline": equity})
    return {
        "ok": True,
        "message": f"Baseline reset to current equity ${equity:.2f}",
        "baseline": equity,
        "baselineGbp": round(_compat_gbp(equity), 2),
        "depositSource": "saved",
    }

def _compat_load_buy_mode():
    data = _compat_read(_COMPAT_BUY_SIZE_FILE, {})
    mode = str(data.get("mode") or os.getenv("BUY_SIZE_MODE", "full")).lower().strip()
    return mode if mode in ("full", "partial") else "full"

def _compat_save_buy_mode(mode):
    mode = str(mode or "full").lower().strip()
    if mode not in ("full", "partial"):
        mode = "full"
    _compat_write(_COMPAT_BUY_SIZE_FILE, {"mode": mode})
    globals()["BUY_SIZE_MODE"] = mode
    globals()["FULL_BUY_WHEN_ONE_POSITION"] = mode == "full"
    return mode

def _compat_buy_preview():
    equity, buying_power = _compat_account_equity()

    try:
        max_positions = int(globals().get("MAX_POSITIONS", 1))
    except Exception:
        max_positions = 1

    try:
        positions = get_positions() if "get_positions" in globals() else []
        open_positions = len(positions)
    except Exception:
        open_positions = 0

    try:
        capped_equity = effective_trading_equity(equity) if "effective_trading_equity" in globals() else equity
    except Exception:
        capped_equity = equity

    try:
        cash_buffer = float(globals().get("CASH_BUFFER", 0.50))
    except Exception:
        cash_buffer = 0.50

    try:
        full_buffer = float(globals().get("FULL_BUY_CASH_BUFFER", 2.00))
    except Exception:
        full_buffer = 2.00

    partial_usd = max(0.0, min(capped_equity / max(1, max_positions), max(0.0, buying_power - cash_buffer)))
    full_usd = max(0.0, min(capped_equity, max(0.0, buying_power - full_buffer)))
    mode = _compat_load_buy_mode()

    return {
        "ok": True,
        "mode": mode,
        "partialUsd": round(partial_usd, 2),
        "partialGbp": round(_compat_gbp(partial_usd), 2),
        "fullUsd": round(full_usd, 2),
        "fullGbp": round(_compat_gbp(full_usd), 2),
        "cappedEquityUsd": round(capped_equity, 2),
        "cappedEquityGbp": round(_compat_gbp(capped_equity), 2),
        "buyingPowerUsd": round(buying_power, 2),
        "buyingPowerGbp": round(_compat_gbp(buying_power), 2),
        "maxPositions": max_positions,
        "openPositions": open_positions,
        "remainingSlots": max(0, max_positions - open_positions),
    }

@app.get("/buy-size-preview")
def compat_buy_size_preview():
    return _compat_buy_preview()

@app.get("/buy-size-mode")
def compat_get_buy_size_mode():
    mode = _compat_load_buy_mode()
    return {
        "ok": True,
        "buySizeMode": mode,
        "fullBuyWhenOnePosition": mode == "full",
        "preview": _compat_buy_preview(),
    }

@app.post("/buy-size-mode")
def compat_post_buy_size_mode(payload: dict = Body(...), request: Request = None):
    _compat_auth(request)
    mode = str(payload.get("mode", "")).lower().strip()
    if mode not in ("full", "partial"):
        raise HTTPException(status_code=400, detail="mode must be full or partial")
    saved = _compat_save_buy_mode(mode)
    return {
        "ok": True,
        "message": f"Buy size mode saved as {saved}",
        "buySizeMode": saved,
        "fullBuyWhenOnePosition": saved == "full",
        "preview": _compat_buy_preview(),
    }



# =========================
# TRADEBOT V5.1 — REPLAY LABORATORY
# =========================
def _v5_replay_variants() -> List[Dict[str, Any]]:
    """Fixed, explainable research variants. None can alter live settings."""
    return [
        {"key": "current_a_plus", "name": "Current A+ thresholds", "confidence": 0.70, "quality": 0.026, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "confidence_068", "name": "Confidence 0.68", "confidence": 0.68, "quality": 0.026, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "confidence_072", "name": "Confidence 0.72", "confidence": 0.72, "quality": 0.026, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "quality_022", "name": "Quality 0.022", "confidence": 0.70, "quality": 0.022, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "quality_030", "name": "Quality 0.030", "confidence": 0.70, "quality": 0.030, "momentum_min": 0.0, "spread_max": 0.010},
        {"key": "no_momentum", "name": "Momentum gate disabled", "confidence": 0.70, "quality": 0.026, "momentum_min": None, "spread_max": 0.010},
        {"key": "relaxed_spread", "name": "Spread max 0.015", "confidence": 0.70, "quality": 0.026, "momentum_min": 0.0, "spread_max": 0.015},
        {"key": "historical_live_decision", "name": "Original approved decisions", "original_approved_only": True},
    ]


def _v5_variant_accepts(row: Dict[str, Any], variant: Dict[str, Any]) -> bool:
    if variant.get("original_approved_only"):
        return str(row.get("decision") or "").upper() == "APPROVED"
    confidence = float(row.get("confidence") or 0.0)
    quality = float(row.get("quality") or 0.0)
    momentum = float(row.get("momentum") or 0.0)
    spread = float(row.get("spread") or 999.0)
    if confidence < float(variant.get("confidence", 0.0)):
        return False
    if quality < float(variant.get("quality", 0.0)):
        return False
    momentum_min = variant.get("momentum_min")
    if momentum_min is not None and momentum < float(momentum_min):
        return False
    if spread > float(variant.get("spread_max", 999.0)):
        return False
    return True


def _v5_replay_metrics(values: List[float]) -> Dict[str, Any]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    wins = [v for v in clean if v > 0]
    losses = [v for v in clean if v < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for value in clean:
        equity += value
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return {
        "trades": len(clean),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": len(wins) / max(1, len(wins) + len(losses)),
        "profitFactor": gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0),
        "expectancyPct": sum(clean) / max(1, len(clean)),
        "totalReturnPct": sum(clean),
        "maxDrawdownPct": max_drawdown,
        "largestWinPct": max(clean) if clean else 0.0,
        "largestLossPct": min(clean) if clean else 0.0,
    }


def v5_run_replay(date_from: Optional[str] = None, date_to: Optional[str] = None,
                  horizon_hours: int = V5_REPLAY_DEFAULT_HORIZON_HOURS,
                  label: Optional[str] = None) -> Dict[str, Any]:
    if not SQLITE_ENABLED:
        return {"ok": False, "message": "SQLite disabled"}
    if not V5_REPLAY_ENABLED:
        return {"ok": False, "message": "V5 replay disabled"}
    horizon = max(1, int(horizon_hours))
    try:
        init_db()
        conn = db_connect()
        where = ["o.status='COMPLETE'", "o.net_return_pct IS NOT NULL", "o.horizon_hours=?"]
        params: List[Any] = [horizon]
        if date_from:
            where.append("d.observed_at>=?")
            params.append(str(date_from))
        if date_to:
            where.append("d.observed_at<=?")
            params.append(str(date_to))
        rows = [dict(r) for r in conn.execute(
            f"""SELECT d.*,o.net_return_pct,o.sample_key,o.evaluated_at
                 FROM v4_market_dna d JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
                 WHERE {' AND '.join(where)} ORDER BY d.observed_at ASC LIMIT ?""",
            tuple(params + [V5_REPLAY_MAX_ROWS]),
        ).fetchall()]
        variants = _v5_replay_variants()
        created_at = datetime.now(UTC).isoformat()
        cur = conn.execute(
            """INSERT INTO v5_replay_runs(created_at,label,date_from,date_to,horizon_hours,observation_count,variant_count,payload_json)
               VALUES(?,?,?,?,?,?,?,?)""",
            (created_at, label or "Replay Laboratory", date_from, date_to, horizon, len(rows), len(variants),
             json.dumps({"advisoryOnly": True, "source": "v4_market_dna+v2_observation_outcomes"})),
        )
        run_id = int(cur.lastrowid)
        results = []
        for variant in variants:
            returns = [float(r["net_return_pct"]) for r in rows if _v5_variant_accepts(r, variant)]
            metrics = _v5_replay_metrics(returns)
            eligible = metrics["trades"] >= V5_REPLAY_MIN_SAMPLES
            result = {"variantKey": variant["key"], "variantName": variant["name"], **metrics,
                      "eligible": eligible, "config": variant}
            results.append(result)
            conn.execute(
                """INSERT OR REPLACE INTO v5_replay_results
                   (run_id,variant_key,variant_name,trades,wins,losses,win_rate,profit_factor,expectancy_pct,
                    total_return_pct,max_drawdown_pct,largest_win_pct,largest_loss_pct,config_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, variant["key"], variant["name"], metrics["trades"], metrics["wins"], metrics["losses"],
                 metrics["winRate"], metrics["profitFactor"], metrics["expectancyPct"], metrics["totalReturnPct"],
                 metrics["maxDrawdownPct"], metrics["largestWinPct"], metrics["largestLossPct"], json.dumps(variant)),
            )
        conn.commit()
        conn.close()
        results.sort(key=lambda x: (bool(x["eligible"]), x["expectancyPct"], x["profitFactor"]), reverse=True)
        best = next((r for r in results if r["eligible"]), None)
        baseline = next((r for r in results if r["variantKey"] == "current_a_plus"), None)
        return {
            "ok": True, "version": "V5.1", "advisoryOnly": True, "runId": run_id,
            "createdAt": created_at, "dateFrom": date_from, "dateTo": date_to,
            "horizonHours": horizon, "observations": len(rows), "minimumSamples": V5_REPLAY_MIN_SAMPLES,
            "bestVariant": best, "baseline": baseline, "leaderboard": results,
            "note": "Replay results are research evidence only. No live threshold or order logic was changed.",
        }
    except Exception as e:
        try:
            conn.close()
        except Exception:
            pass
        return {"ok": False, "version": "V5.1", "error": str(e)}


def v5_replay_leaderboard(run_id: Optional[int] = None, limit: int = 25) -> Dict[str, Any]:
    try:
        init_db(); conn = db_connect()
        if run_id is None:
            row = conn.execute("SELECT id FROM v5_replay_runs ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                conn.close(); return {"ok": True, "version": "V5.1", "runs": 0, "leaderboard": []}
            run_id = int(row["id"])
        run = conn.execute("SELECT * FROM v5_replay_runs WHERE id=?", (int(run_id),)).fetchone()
        if not run:
            conn.close(); return {"ok": False, "message": "Replay run not found", "runId": int(run_id)}
        rows = [dict(r) for r in conn.execute(
            """SELECT * FROM v5_replay_results WHERE run_id=?
               ORDER BY expectancy_pct DESC, profit_factor DESC LIMIT ?""", (int(run_id), max(1, min(int(limit), 100)))).fetchall()]
        conn.close()
        for row in rows:
            try: row["config"] = json.loads(row.pop("config_json") or "{}")
            except Exception: row["config"] = {}
        return {"ok": True, "version": "V5.1", "advisoryOnly": True, "run": dict(run), "leaderboard": rows}
    except Exception as e:
        return {"ok": False, "version": "V5.1", "error": str(e)}


def v5_status_payload() -> Dict[str, Any]:
    try:
        init_db(); conn = db_connect()
        run_count = int(conn.execute("SELECT COUNT(*) FROM v5_replay_runs").fetchone()[0])
        latest = conn.execute("SELECT * FROM v5_replay_runs ORDER BY id DESC LIMIT 1").fetchone()
        observation_count = int(conn.execute(
            """SELECT COUNT(*) FROM v4_market_dna d JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL""").fetchone()[0])
        conn.close()
    except Exception:
        run_count, latest, observation_count = 0, None, 0
    return {"ok": True, "version": "V5.1", "mode": "advisory-replay-laboratory",
            "enabled": V5_REPLAY_ENABLED, "advisoryOnly": True, "liveGateChanged": False,
            "completedObservations": observation_count, "replayRuns": run_count,
            "latestRun": dict(latest) if latest else None,
            "features": {"candidateCapture": True, "historicalReplay": True, "strategyVariants": True,
                         "persistentLeaderboards": True, "automaticLiveChanges": False},
            "rules": {"defaultHorizonHours": V5_REPLAY_DEFAULT_HORIZON_HOURS,
                      "minimumSamples": V5_REPLAY_MIN_SAMPLES, "maxRowsPerReplay": V5_REPLAY_MAX_ROWS}}


@app.get("/v5/status")
def api_v5_status():
    return v5_status_payload()


@app.post("/v5/replay/run")
def api_v5_replay_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v5_run_replay(payload.get("dateFrom"), payload.get("dateTo"),
                         int(payload.get("horizonHours") or V5_REPLAY_DEFAULT_HORIZON_HOURS),
                         payload.get("label"))


@app.get("/v5/replay/leaderboard")
def api_v5_replay_leaderboard(run_id: Optional[int] = None, limit: int = 25):
    return v5_replay_leaderboard(run_id, limit)


@app.post("/v5/replay/day")
def api_v5_replay_day(request: Request, day: str, horizon_hours: int = V5_REPLAY_DEFAULT_HORIZON_HOURS):
    verify_api_key(request)
    start = f"{day}T00:00:00+00:00"
    end = f"{day}T23:59:59.999999+00:00"
    return v5_run_replay(start, end, horizon_hours, f"Daily replay {day}")



# =========================
# TRADEBOT V6.4 — OUTCOME-TIME FORENSICS + VALIDATED SHADOW ENGINE
# =========================
def _v6_brains() -> List[Dict[str, Any]]:
    """Configuration-driven research brains. They observe only; none can place orders."""
    return [
        {"key":"current_a_plus","name":"Current A+","min_confidence":0.70,"min_quality":0.026,"max_spread":0.010,"momentum_min":0.0},
        {"key":"conservative","name":"Conservative","min_confidence":0.78,"min_quality":0.032,"max_spread":0.007,"momentum_min":0.0},
        {"key":"aggressive","name":"Aggressive","min_confidence":0.62,"min_quality":0.018,"max_spread":0.015,"momentum_min":-0.01},
        {"key":"momentum","name":"Momentum","min_confidence":0.68,"min_quality":0.024,"max_spread":0.012,"momentum_min":0.012},
        {"key":"mean_reversion","name":"Mean Reversion","min_confidence":0.64,"min_quality":0.020,"max_spread":0.010,"pullback_min":0.010,"momentum_max":0.010},
        {"key":"breakout","name":"Breakout","min_confidence":0.72,"min_quality":0.030,"max_spread":0.012,"momentum_min":0.020},
    ]


def _v6_accepts(row: Dict[str, Any], brain: Dict[str, Any]) -> bool:
    """Apply a brain to a valid, independent, entry-ready observation."""
    if not bool(int(row.get("ready_to_buy") or 0)):
        return False
    confidence=float(row.get("confidence") or 0.0); quality=float(row.get("quality") or 0.0)
    momentum=float(row.get("momentum") or 0.0); pullback=float(row.get("pullback") or 0.0)
    spread=float(row.get("spread") if row.get("spread") is not None else 999.0)
    if confidence < float(brain.get("min_confidence",0.0)): return False
    if quality < float(brain.get("min_quality",0.0)): return False
    if spread > float(brain.get("max_spread",999.0)): return False
    if "momentum_min" in brain and momentum < float(brain["momentum_min"]): return False
    if "momentum_max" in brain and momentum > float(brain["momentum_max"]): return False
    if "pullback_min" in brain and pullback < float(brain["pullback_min"]): return False
    return True


def _v6_validate_source_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one outcome before it is allowed into brain fitness calculations."""
    reasons: List[str] = []
    entry=float(row.get("entry_price") or 0.0)
    outcome=float(row.get("outcome_price") or 0.0)
    raw=float(row.get("raw_return_pct") or 0.0)
    net=float(row.get("net_return_pct") or 0.0)
    cost=max(0.0,float(row.get("estimated_cost_pct") or 0.0))
    if entry <= 0: reasons.append("missing_or_invalid_entry_price")
    if outcome <= 0: reasons.append("missing_or_invalid_outcome_price")
    if not bool(int(row.get("ready_to_buy") or 0)): reasons.append("entry_trigger_not_ready")
    due_at=row.get("due_at"); bar_at=row.get("outcome_bar_at"); source=str(row.get("outcome_source") or "")
    if source != "alpaca_historical_1min_close": reasons.append("outcome_not_historical_checkpoint")
    if not bar_at: reasons.append("outcome_timestamp_missing")
    if due_at and bar_at:
        try:
            delay=(_v6_parse_utc(bar_at)-_v6_parse_utc(due_at)).total_seconds()/60.0
            if delay < -V6_HISTORICAL_BAR_LOOKBACK_MINUTES: reasons.append("outcome_timestamp_before_allowed_window")
            if delay > V6_OUTCOME_MAX_DELAY_MINUTES: reasons.append("outcome_evaluated_too_late")
        except Exception: reasons.append("outcome_timestamp_mismatch")
    if entry > 0 and outcome > 0:
        expected=((outcome/entry)-1.0)*100.0
        if abs(expected-raw) > 0.02: reasons.append("raw_return_formula_mismatch")
        if abs((raw-cost)-net) > 0.02: reasons.append("net_return_formula_mismatch")
    if not math.isfinite(net): reasons.append("non_finite_return")
    if abs(net) > 50.0: reasons.append("implausible_return_over_50pct")
    return {"valid":not reasons,"reasons":reasons}


def _v6_source_rows(horizon_hours: int, limit: int) -> List[Dict[str, Any]]:
    """Return independent observations only—one row per sample bucket and horizon."""
    init_db(); conn=db_connect()
    rows=[dict(r) for r in conn.execute(
        """WITH ranked AS (
               SELECT d.*, o.entry_price, o.outcome_price,
                      o.return_pct AS raw_return_pct, o.net_return_pct,
                      o.estimated_cost_pct, o.sample_key, o.due_at, o.evaluated_at,
                      o.evaluation_delay_minutes, o.outcome_bar_at, o.outcome_source, o.repaired_at,
                      ROW_NUMBER() OVER (
                          PARTITION BY COALESCE(o.sample_key, CAST(o.decision_id AS TEXT)), o.horizon_hours
                          ORDER BY o.id ASC
                      ) AS rn
               FROM v4_market_dna d
               JOIN v2_observation_outcomes o ON o.decision_id=d.decision_id
               WHERE o.status='COMPLETE' AND o.net_return_pct IS NOT NULL
                 AND o.horizon_hours=?
           )
           SELECT * FROM ranked WHERE rn=1 ORDER BY observed_at ASC LIMIT ?""",
        (max(1,int(horizon_hours)),max(1,min(int(limit),50000)))).fetchall()]
    conn.close()
    return rows


def v6_validation_report(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = 50000) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours)); rows=_v6_source_rows(horizon,limit)
    reason_counts: Dict[str,int]={}; valid=0; entry_ready=0
    samples=[]
    for row in rows:
        check=_v6_validate_source_row(row)
        if bool(int(row.get("ready_to_buy") or 0)): entry_ready += 1
        if check["valid"]: valid += 1
        else:
            for reason in check["reasons"]: reason_counts[reason]=reason_counts.get(reason,0)+1
            if len(samples)<20:
                samples.append({"decisionId":row.get("decision_id"),"symbol":row.get("symbol"),
                                "observedAt":row.get("observed_at"),"reasons":check["reasons"],
                                "entryPrice":row.get("entry_price"),"outcomePrice":row.get("outcome_price"),
                                "rawReturnPct":row.get("raw_return_pct"),"netReturnPct":row.get("net_return_pct"),
                                "dueAt":row.get("due_at"),"outcomeBarAt":row.get("outcome_bar_at"),
                                "outcomeSource":row.get("outcome_source"),"evaluationDelayMinutes":row.get("evaluation_delay_minutes")})
    return {"ok":True,"version":"V6.4","advisoryOnly":True,"horizonHours":horizon,
            "independentSourceObservations":len(rows),"entryReadyObservations":entry_ready,
            "validLearningObservations":valid,"invalidLearningObservations":len(rows)-valid,
            "invalidReasons":reason_counts,"invalidSamples":samples,
            "rules":{"independentSampleBuckets":True,"requiresEntryTriggerReady":True,
                     "returnFormulaTolerancePct":0.02,"maximumAbsoluteReturnPct":50.0,
                     "historicalCheckpointRequired":True,"maximumOutcomeDelayMinutes":V6_OUTCOME_MAX_DELAY_MINUTES}}


def v6_sync_brains(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = 10000) -> Dict[str, Any]:
    if not SQLITE_ENABLED: return {"ok":False,"message":"SQLite disabled"}
    if not V6_BRAINS_ENABLED: return {"ok":False,"message":"V6 brains disabled"}
    horizon=max(1,int(horizon_hours)); limit=max(1,min(int(limit),50000))
    try:
        rows=_v6_source_rows(horizon,limit)
        conn=db_connect(); brains=_v6_brains(); inserted=0; accepted=0; valid_rows=0; rejected_invalid=0
        now=datetime.now(UTC).isoformat()
        for row in rows:
            validation=_v6_validate_source_row(row)
            if not validation["valid"]:
                rejected_invalid += 1
                continue
            valid_rows += 1
            for brain in brains:
                passed=1 if _v6_accepts(row,brain) else 0
                accepted += passed
                before=conn.total_changes
                conn.execute("""INSERT OR IGNORE INTO v6_brain_observations
                    (brain_key,brain_name,decision_id,symbol,observed_at,market_regime,horizon_hours,accepted,return_pct,confidence,quality,momentum,pullback,spread,config_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (brain["key"],brain["name"],int(row["decision_id"]),row.get("symbol") or "",row.get("observed_at") or now,
                     row.get("market_regime") or "unknown",horizon,passed,float(row["net_return_pct"]),
                     float(row.get("confidence") or 0),float(row.get("quality") or 0),float(row.get("momentum") or 0),
                     float(row.get("pullback") or 0),float(row.get("spread") or 0),json.dumps(brain),now))
                inserted += conn.total_changes-before
        conn.commit(); conn.close()
        return {"ok":True,"version":"V6.4","advisoryOnly":True,"horizonHours":horizon,
                "independentSourceObservations":len(rows),"validLearningObservations":valid_rows,
                "invalidObservationsRejected":rejected_invalid,"brains":len(brains),
                "newShadowRows":inserted,"acceptedEvaluations":accepted,"liveGateChanged":False}
    except Exception as e:
        try: conn.close()
        except Exception: pass
        return {"ok":False,"version":"V6.4","error":str(e)}


def v6_rebuild_validated(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = V6_AUTO_SYNC_LIMIT) -> Dict[str, Any]:
    """Delete legacy V6.2 shadow rows and rebuild only from validated V6.3 evidence."""
    try:
        init_db(); conn=db_connect()
        removed=int(conn.execute("SELECT COUNT(*) FROM v6_brain_observations WHERE horizon_hours=?",(int(horizon_hours),)).fetchone()[0])
        conn.execute("DELETE FROM v6_brain_observations WHERE horizon_hours=?",(int(horizon_hours),))
        conn.commit(); conn.close()
        result=v6_sync_brains(horizon_hours,limit)
        return {**result,"rebuild":True,"legacyRowsRemoved":removed,
                "note":"Research rows only were rebuilt. Live trading logic was unchanged."}
    except Exception as e:
        return {"ok":False,"version":"V6.4","error":str(e)}


def v6_auto_sync_worker() -> None:
    """Continuously sync validated, independent outcomes into every research brain."""
    global v6_last_sync_result
    first_run = True
    while True:
        try:
            result = v6_sync_brains(V6_DEFAULT_HORIZON_HOURS, V6_AUTO_SYNC_LIMIT)
            result["automatic"] = True; result["ranAt"] = datetime.now(UTC).isoformat()
            v6_last_sync_result = result
            if first_run or int(result.get("newShadowRows") or 0) > 0:
                print("V6.4 AUTO SYNC | "
                      f"source={result.get('independentSourceObservations', 0)} "
                      f"valid={result.get('validLearningObservations', 0)} "
                      f"new={result.get('newShadowRows', 0)} accepted={result.get('acceptedEvaluations', 0)}")
            first_run = False
        except Exception as exc:
            v6_last_sync_result = {"ok":False,"automatic":True,"ranAt":datetime.now(UTC).isoformat(),"error":str(exc)}
            print(f"V6.4 AUTO SYNC ERROR: {exc}")
        time.sleep(V6_AUTO_SYNC_INTERVAL_SECONDS)


def _v6_score_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    values=[float(r["return_pct"]) for r in rows if r.get("return_pct") is not None and math.isfinite(float(r["return_pct"]))]
    metrics=_v5_replay_metrics(values)
    n=int(metrics.get("trades") or 0)
    expectancy=float(metrics.get("expectancyPct") or 0.0)
    # Standard error gives the leaderboard a simple sample-stability measure.
    if n > 1:
        mean=sum(values)/n
        variance=sum((x-mean)**2 for x in values)/(n-1)
        std=math.sqrt(max(0.0,variance)); standard_error=std/math.sqrt(n)
    else:
        std=0.0; standard_error=999.0 if n == 0 else 0.0
    metrics.update({"returnStdDevPct":std,"expectancyStandardErrorPct":standard_error,
                    "expectancyLower95Pct":expectancy-(1.96*standard_error) if n>1 else expectancy})
    return metrics


def _v6_research_score(metrics: Dict[str, Any]) -> float:
    n=max(0,int(metrics.get("trades") or 0)); expectancy=float(metrics.get("expectancyPct") or 0.0)
    pf=max(0.0,min(float(metrics.get("profitFactor") or 0.0),3.0))
    drawdown=max(0.0,float(metrics.get("maxDrawdownPct") or 0.0))
    lower=float(metrics.get("expectancyLower95Pct") or expectancy)
    sample_confidence=min(1.0,math.sqrt(n/max(1.0,float(V6_MIN_SAMPLES*4))))
    return ((expectancy*0.45)+(lower*0.35)+(max(0.0,pf-1.0)*0.20)-(drawdown*0.01))*sample_confidence


def v6_brain_scoreboard(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, regime: Optional[str] = None) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours))
    try:
        init_db(); conn=db_connect(); params=[horizon]; extra=""
        if regime: extra=" AND lower(market_regime)=lower(?)"; params.append(regime)
        rows=[dict(r) for r in conn.execute(
            f"SELECT * FROM v6_brain_observations WHERE horizon_hours=? AND accepted=1{extra} ORDER BY observed_at",tuple(params)).fetchall()]
        conn.close(); by={}
        for r in rows: by.setdefault(r["brain_key"],[]).append(r)
        configs={b["key"]:b for b in _v6_brains()}; board=[]
        for key,brain in configs.items():
            metrics=_v6_score_rows(by.get(key,[])); sample_eligible=metrics["trades"]>=V6_MIN_SAMPLES
            recommendation_eligible=(sample_eligible and metrics["profitFactor"]>=V6_RECOMMENDATION_MIN_PF
                                     and metrics["expectancyPct"]>=V6_RECOMMENDATION_MIN_EXPECTANCY
                                     and metrics["expectancyLower95Pct"]>0)
            score=_v6_research_score(metrics) if sample_eligible else -999.0
            health="HEALTHY" if recommendation_eligible else ("LOSING" if sample_eligible and metrics["expectancyPct"]<0 else "INSUFFICIENT")
            board.append({"brainKey":key,"brainName":brain["name"],**metrics,
                          "eligible":recommendation_eligible,"sampleEligible":sample_eligible,
                          "recommendationEligible":recommendation_eligible,"health":health,
                          "researchScore":score,"config":brain})
        board.sort(key=lambda x:(x["recommendationEligible"],x["researchScore"],x["trades"]),reverse=True)
        leader=next((x for x in board if x["recommendationEligible"]),None)
        research_leader=next((x for x in board if x["sampleEligible"]),None)
        return {"ok":True,"version":"V6.4","advisoryOnly":True,"horizonHours":horizon,"marketRegime":regime,
                "minimumSamples":V6_MIN_SAMPLES,"leader":leader,"researchLeader":research_leader,
                "healthyLeaderAvailable":leader is not None,
                "leaderRule":"A leader must pass samples, profit factor, expectancy and positive 95% lower expectancy bound.",
                "scoreboard":board}
    except Exception as e: return {"ok":False,"version":"V6.4","error":str(e)}


def v6_recommendation(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, regime: Optional[str] = None, persist: bool = True) -> Dict[str, Any]:
    board=v6_brain_scoreboard(horizon_hours,regime)
    if not board.get("ok"): return board
    eligible=[x for x in board["scoreboard"] if x["recommendationEligible"]]
    best=eligible[0] if eligible else None
    current=next((x for x in board["scoreboard"] if x["brainKey"]==V6_ACTIVE_BRAIN),None)
    action="KEEP_CURRENT"
    if best and best["brainKey"]!=V6_ACTIVE_BRAIN:
        if not current or not current["recommendationEligible"] or best["researchScore"] > current["researchScore"]*1.10:
            action="RECOMMEND_SWITCH"
    samples=int(best["trades"] if best else 0)
    grade="HIGH" if best and samples>=50 else ("MEDIUM" if best and samples>=25 else ("LOW" if best else "INSUFFICIENT"))
    payload={"ok":True,"version":"V6.4","advisoryOnly":True,"automaticLiveChanges":False,"action":action,
             "currentBrain":V6_ACTIVE_BRAIN,"recommendedBrain":best["brainKey"] if best else None,
             "confidenceGrade":grade,"marketRegime":regime,"horizonHours":int(horizon_hours),
             "leader":best,"current":current,"safeguards":{"minimumSamples":V6_MIN_SAMPLES,
             "minimumProfitFactor":V6_RECOMMENDATION_MIN_PF,"minimumExpectancyPct":V6_RECOMMENDATION_MIN_EXPECTANCY,
             "positive95PctLowerBoundRequired":True,"requiredImprovement":0.10},
             "note":"Recommendation only. No live strategy or order gate was changed."}
    if persist and SQLITE_ENABLED:
        try:
            conn=db_connect(); conn.execute("""INSERT INTO v6_recommendations
                (created_at,horizon_hours,market_regime,current_brain,recommended_brain,confidence_grade,approved,payload_json)
                VALUES(?,?,?,?,?,?,0,?)""",(datetime.now(UTC).isoformat(),int(horizon_hours),regime,V6_ACTIVE_BRAIN,
                payload["recommendedBrain"],grade,json.dumps(payload))); conn.commit(); conn.close()
        except Exception: pass
    return payload


def v6_status_payload() -> Dict[str, Any]:
    try:
        init_db(); conn=db_connect()
        shadow_rows=int(conn.execute("SELECT COUNT(*) FROM v6_brain_observations").fetchone()[0])
        accepted_rows=int(conn.execute("SELECT COUNT(*) FROM v6_brain_observations WHERE accepted=1").fetchone()[0])
        latest=conn.execute("SELECT created_at FROM v6_brain_observations ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
        validation=v6_validation_report(V6_DEFAULT_HORIZON_HOURS,V6_AUTO_SYNC_LIMIT)
        source_rows=int(validation.get("independentSourceObservations") or 0)
    except Exception:
        shadow_rows,accepted_rows,source_rows,latest,validation=0,0,0,None,{"ok":False}
    return {"ok":True,"version":"V6.4","mode":"historical-checkpoint-validated-shadow-intelligence","enabled":V6_BRAINS_ENABLED,
            "advisoryOnly":True,"automaticLiveChanges":False,"liveGateChanged":False,"activeBrain":V6_ACTIVE_BRAIN,
            "brainCount":len(_v6_brains()),"sourceCompletedObservations":source_rows,
            "validLearningObservations":validation.get("validLearningObservations",0),
            "invalidLearningObservations":validation.get("invalidLearningObservations",0),
            "shadowEvaluations":shadow_rows,"acceptedShadowEvaluations":accepted_rows,
            "latestShadowAt":latest["created_at"] if latest else None,"lastAutomaticSync":v6_last_sync_result or None,
            "features":{"configurationDrivenBrains":True,"multiBrainShadowing":True,"regimeScoreboards":True,
                        "guardedRecommendations":True,"automaticHistoricalBootstrap":True,
                        "continuousOutcomeSync":True,"historicalCheckpointOutcomes":True,"outcomeTimeRepair":True,
                        "independentSampleDedupe":True,
                        "entryTriggerValidation":True,"returnFormulaValidation":True,
                        "confidenceBoundRanking":True,"selfGeneratedBrains":False,"automaticPromotion":False},
            "rules":{"defaultHorizonHours":V6_DEFAULT_HORIZON_HOURS,"minimumSamples":V6_MIN_SAMPLES,
                     "minimumProfitFactor":V6_RECOMMENDATION_MIN_PF,"minimumExpectancyPct":V6_RECOMMENDATION_MIN_EXPECTANCY,
                     "autoSyncEnabled":V6_AUTO_SYNC_ENABLED,"autoSyncIntervalSeconds":V6_AUTO_SYNC_INTERVAL_SECONDS,
                     "autoSyncLimit":V6_AUTO_SYNC_LIMIT,"maximumOutcomeDelayMinutes":V6_OUTCOME_MAX_DELAY_MINUTES,
                     "repairBatchSize":V6_REPAIR_BATCH_SIZE}}


@app.get("/v6/status")
def api_v6_status(): return v6_status_payload()

@app.get("/v6/validation")
def api_v6_validation(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, limit: int = V6_AUTO_SYNC_LIMIT):
    return v6_validation_report(horizon_hours,limit)

@app.post("/v6/outcomes/repair")
def api_v6_outcomes_repair(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v6_repair_outcome_times(int(payload.get("horizonHours") or V6_DEFAULT_HORIZON_HOURS),
                                   int(payload.get("limit") or V6_REPAIR_BATCH_SIZE))


@app.post("/v6/brains/sync")
def api_v6_brains_sync(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v6_sync_brains(int(payload.get("horizonHours") or V6_DEFAULT_HORIZON_HOURS),int(payload.get("limit") or 10000))

@app.post("/v6/rebuild")
def api_v6_rebuild(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v6_rebuild_validated(int(payload.get("horizonHours") or V6_DEFAULT_HORIZON_HOURS),
                                int(payload.get("limit") or V6_AUTO_SYNC_LIMIT))

@app.get("/v6/brains")
def api_v6_brains(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, regime: Optional[str] = None):
    return v6_brain_scoreboard(horizon_hours,regime)

@app.get("/v6/recommendation")
def api_v6_recommendation(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, regime: Optional[str] = None):
    return v6_recommendation(horizon_hours,regime,False)

@app.post("/v6/recommendation/run")
def api_v6_recommendation_run(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request)
    return v6_recommendation(int(payload.get("horizonHours") or V6_DEFAULT_HORIZON_HOURS),payload.get("regime"),True)


# =========================
# TRADEBOT V7.1 — EVIDENCE-DRIVEN RESEARCH FACTORY
# =========================
V7_VERSION = "V7.1"


def _v7_ensure_tables() -> None:
    if not SQLITE_ENABLED:
        return
    init_db(); conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_brains (
        brain_key TEXT PRIMARY KEY, brain_name TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
        parent_key TEXT, status TEXT NOT NULL DEFAULT 'ACTIVE', created_at TEXT NOT NULL,
        retired_at TEXT, config_json TEXT NOT NULL, origin TEXT NOT NULL DEFAULT 'seed',
        last_evaluated_at TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_evolution_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, completed_at TEXT,
        horizon_hours INTEGER NOT NULL, parent_count INTEGER NOT NULL DEFAULT 0,
        children_created INTEGER NOT NULL DEFAULT 0, brains_retired INTEGER NOT NULL DEFAULT 0,
        champion_key TEXT, payload_json TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_brain_results (
        brain_key TEXT NOT NULL, horizon_hours INTEGER NOT NULL, evaluated_at TEXT NOT NULL,
        trades INTEGER NOT NULL DEFAULT 0, wins INTEGER NOT NULL DEFAULT 0, losses INTEGER NOT NULL DEFAULT 0,
        win_rate REAL, profit_factor REAL, expectancy_pct REAL, expectancy_lower95_pct REAL,
        max_drawdown_pct REAL, research_score REAL, eligible INTEGER NOT NULL DEFAULT 0,
        accepted_decision_ids_json TEXT, PRIMARY KEY(brain_key, horizon_hours))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_maintenance_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, completed_at TEXT,
        trigger TEXT NOT NULL, repaired INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0,
        rebuild_json TEXT, evolution_json TEXT, ok INTEGER NOT NULL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v7_research_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, horizon_hours INTEGER NOT NULL,
        source_observations INTEGER NOT NULL DEFAULT 0, valid_observations INTEGER NOT NULL DEFAULT 0,
        candidates_created INTEGER NOT NULL DEFAULT 0, payload_json TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v7_brains_status ON v7_brains(status, generation)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v7_results_score ON v7_brain_results(horizon_hours, research_score)")
    now = datetime.now(UTC).isoformat()
    for brain in _v6_brains():
        conn.execute("""INSERT OR IGNORE INTO v7_brains
            (brain_key,brain_name,generation,parent_key,status,created_at,config_json,origin)
            VALUES(?,?,0,NULL,'ACTIVE',?,?,'v6_seed')""",
            (brain['key'], brain['name'], now, json.dumps(brain, sort_keys=True)))
    conn.commit(); conn.close()


def _v7_active_brains() -> List[Dict[str, Any]]:
    _v7_ensure_tables(); conn=db_connect()
    rows=conn.execute("SELECT * FROM v7_brains WHERE status='ACTIVE' ORDER BY generation, created_at").fetchall(); conn.close()
    out=[]
    for row in rows:
        item=dict(row)
        try: item['config']=json.loads(item.pop('config_json'))
        except Exception: item['config']={}
        out.append(item)
    return out


def _v7_valid_rows(horizon: int) -> List[Dict[str, Any]]:
    return [r for r in _v6_source_rows(horizon,V6_AUTO_SYNC_LIMIT) if _v6_validate_source_row(r).get('valid')]


def _v7_evaluate_brain(brain: Dict[str, Any], source_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    cfg=brain.get('config') or brain; accepted=[]
    for row in source_rows:
        if _v6_accepts(row,cfg):
            accepted.append({'decision_id':int(row.get('decision_id') or 0),
                'return_pct':float(row.get('net_return_pct') or 0.0),
                'confidence':float(row.get('confidence') or 0.0)})
    metrics=_v6_score_rows(accepted)
    sample_ok=metrics['trades'] >= V7_MIN_PARENT_SAMPLES
    eligible=(sample_ok and metrics['profitFactor'] >= V6_RECOMMENDATION_MIN_PF
              and metrics['expectancyPct'] >= V6_RECOMMENDATION_MIN_EXPECTANCY
              and metrics['expectancyLower95Pct'] > 0)
    score=_v6_research_score(metrics) if metrics['trades'] >= V6_MIN_SAMPLES else -999.0
    return {**metrics,'eligible':eligible,'researchScore':score,
            'acceptedDecisionIds':[x['decision_id'] for x in accepted]}


def _v7_quantile(values: List[float], q: float) -> float:
    if not values: return 0.0
    vals=sorted(float(x) for x in values); pos=(len(vals)-1)*q; lo=int(math.floor(pos)); hi=int(math.ceil(pos))
    return vals[lo] if lo==hi else vals[lo]+(vals[hi]-vals[lo])*(pos-lo)


def _v7_segment_metrics(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _v6_score_rows([{'return_pct':float(r.get('net_return_pct') or 0.0)} for r in rows])


def v7_research_insights(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours)); source=_v6_source_rows(horizon,V6_AUTO_SYNC_LIMIT); rows=_v7_valid_rows(horizon)
    features=['confidence','quality','momentum','pullback','spread']
    feature_report=[]
    for feature in features:
        vals=[float(r.get(feature) or 0.0) for r in rows]
        cuts=sorted(set(round(_v7_quantile(vals,q),6) for q in (0.2,0.4,0.6,0.8)))
        segments=[]
        for cut in cuts:
            high=[r for r in rows if float(r.get(feature) or 0.0)>=cut]
            low=[r for r in rows if float(r.get(feature) or 0.0)<=cut]
            for direction,group in [('at_or_above',high),('at_or_below',low)]:
                m=_v7_segment_metrics(group)
                if m['trades']>=max(5,min(V6_MIN_SAMPLES,10)):
                    segments.append({'direction':direction,'threshold':cut,**m})
        segments.sort(key=lambda x:(x['expectancyPct'],x['profitFactor'],x['trades']),reverse=True)
        feature_report.append({'feature':feature,'bestSegments':segments[:4]})
    regimes=[]
    by_regime={}
    for r in rows: by_regime.setdefault(str(r.get('market_regime') or 'unknown').lower(),[]).append(r)
    for name,group in by_regime.items(): regimes.append({'regime':name,**_v7_segment_metrics(group)})
    regimes.sort(key=lambda x:(x['expectancyPct'],x['trades']),reverse=True)
    wins=[r for r in rows if float(r.get('net_return_pct') or 0)>0]; losses=[r for r in rows if float(r.get('net_return_pct') or 0)<=0]
    contrasts=[]
    for f in features:
        contrasts.append({'feature':f,
            'winnerMedian':round(_v7_quantile([float(r.get(f) or 0) for r in wins],.5),6),
            'loserMedian':round(_v7_quantile([float(r.get(f) or 0) for r in losses],.5),6)})
    overall=_v7_segment_metrics(rows)
    return {'ok':True,'version':V7_VERSION,'advisoryOnly':True,'horizonHours':horizon,
            'sourceObservations':len(source),'validObservations':len(rows),'invalidObservations':len(source)-len(rows),
            'overall':overall,'winnerLoserContrasts':contrasts,'featureAnalysis':feature_report,
            'regimeAnalysis':regimes,'note':'Descriptive research only; no live setting was changed.'}


def _v7_candidate_grid(rows: List[Dict[str, Any]], max_candidates: int) -> List[Dict[str, Any]]:
    if not rows: return []
    quantiles={f:sorted(set(round(_v7_quantile([float(r.get(f) or 0) for r in rows],q),4)
                      for q in (.2,.4,.6,.8))) for f in ('confidence','quality','momentum','pullback','spread')}
    configs=[]
    # Evidence-driven threshold families. Spread uses an upper bound; confidence/quality use lower bounds.
    for conf in quantiles['confidence']:
      for qual in quantiles['quality']:
       for spread in quantiles['spread']:
        configs.append({'min_confidence':conf,'min_quality':qual,'max_spread':spread})
    for mom in quantiles['momentum']:
      for conf in quantiles['confidence'][1:]:
       for spread in quantiles['spread']:
        configs.append({'min_confidence':conf,'min_quality':quantiles['quality'][1],
                        'max_spread':spread,'momentum_min':mom})
    for pull in quantiles['pullback']:
      for mommax in quantiles['momentum']:
       configs.append({'min_confidence':quantiles['confidence'][0],'min_quality':quantiles['quality'][0],
                       'max_spread':quantiles['spread'][2],'pullback_min':pull,'momentum_max':mommax})
    scored=[]; seen=set()
    min_samples=max(8,min(V7_MIN_PARENT_SAMPLES,15))
    for cfg in configs:
        sig=json.dumps(cfg,sort_keys=True)
        if sig in seen: continue
        seen.add(sig)
        result=_v7_evaluate_brain(cfg,rows)
        if result['trades']<min_samples: continue
        # Discovery score rewards expectancy and PF but strongly penalises drawdown and uncertainty.
        discovery=(result['expectancyPct']*0.55 + result['expectancyLower95Pct']*0.25
                   + min(result['profitFactor'],3.0)*0.15 - result['maxDrawdownPct']*0.01)
        scored.append((discovery,result,cfg))
    scored.sort(key=lambda x:(x[0],x[1]['expectancyPct'],x[1]['profitFactor']),reverse=True)
    diverse=[]
    for score,result,cfg in scored:
        if any(sum(1 for k,v in cfg.items() if other['config'].get(k)==v)>=max(2,len(cfg)-1) for other in diverse):
            continue
        diverse.append({'discoveryScore':score,'result':result,'config':cfg})
        if len(diverse)>=max_candidates: break
    return diverse


def v7_discover(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, candidates: int = 12) -> Dict[str, Any]:
    _v7_ensure_tables(); horizon=max(1,int(horizon_hours)); count=max(1,min(int(candidates),30)); rows=_v7_valid_rows(horizon)
    found=_v7_candidate_grid(rows,count); conn=db_connect(); now=datetime.now(UTC).isoformat()
    max_gen=int(conn.execute("SELECT COALESCE(MAX(generation),0) FROM v7_brains").fetchone()[0]); generation=max_gen+1; created=[]
    for i,item in enumerate(found,1):
        cfg=dict(item['config']); suffix=secrets.token_hex(3); key=f"discovery_g{generation}_{suffix}"
        cfg.update({'key':key,'name':f"Evidence Discovery G{generation}.{i}",'research_only':True,
                    'discovery_score':round(item['discoveryScore'],6)})
        conn.execute("""INSERT OR IGNORE INTO v7_brains
            (brain_key,brain_name,generation,parent_key,status,created_at,config_json,origin)
            VALUES(?,?,?,NULL,'ACTIVE',?,?,'evidence_discovery')""",
            (key,cfg['name'],generation,now,json.dumps(cfg,sort_keys=True)))
        created.append({'brainKey':key,'brainName':cfg['name'],'config':cfg,'backtest':item['result']})
    payload={'ok':True,'version':V7_VERSION,'advisoryOnly':True,'automaticLiveChanges':False,
             'horizonHours':horizon,'validObservations':len(rows),'generation':generation,
             'candidatesCreated':len(created),'candidates':created,
             'healthyCandidates':sum(1 for x in created if x['backtest'].get('eligible')),
             'note':'Candidates were derived from observed feature thresholds. They remain shadow-only.'}
    cur=conn.execute("""INSERT INTO v7_research_runs
        (created_at,horizon_hours,source_observations,valid_observations,candidates_created,payload_json)
        VALUES(?,?,?,?,?,?)""",(now,horizon,len(_v6_source_rows(horizon,V6_AUTO_SYNC_LIMIT)),len(rows),len(created),json.dumps(payload)))
    payload['researchRunId']=int(cur.lastrowid); conn.commit(); conn.close(); return payload


def _v7_mutate_config(parent: Dict[str, Any], child_number: int, generation: int) -> Dict[str, Any]:
    cfg={k:v for k,v in dict(parent).items() if k not in ('discovery_score',)}; parent_key=str(cfg.get('key') or 'brain')
    rng=random.Random(f"{parent_key}:{generation}:{child_number}:{datetime.now(UTC).date().isoformat()}")
    ranges={'min_confidence':(0.50,0.90,0.04),'min_quality':(0.010,0.060,0.004),
            'max_spread':(0.004,0.025,0.002),'momentum_min':(-0.025,0.050,0.006),
            'momentum_max':(-0.010,0.035,0.006),'pullback_min':(0.000,0.050,0.005)}
    mutable=[k for k in ranges if k in cfg] or ['min_confidence','min_quality','max_spread']
    for key in rng.sample(mutable,min(1 if rng.random()>.25 else 2,len(mutable))):
        lo,hi,step=ranges[key]; current=float(cfg.get(key,(lo+hi)/2)); current += step*(.5+rng.random())*(1 if rng.random()>=.5 else -1)
        cfg[key]=round(max(lo,min(hi,current)),4)
    suffix=secrets.token_hex(3); cfg['key']=f"{parent_key}_g{generation}_{suffix}"
    cfg['name']=f"{parent.get('name',parent_key)} G{generation}.{child_number}"; cfg['research_only']=True
    return cfg


def v7_evolve(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, children: int = V7_CHILDREN_PER_RUN) -> Dict[str, Any]:
    if not V7_ENABLED: return {'ok':False,'version':V7_VERSION,'message':'V7 disabled'}
    _v7_ensure_tables(); horizon=max(1,int(horizon_hours)); child_count=max(1,min(int(children),50)); source=_v7_valid_rows(horizon)
    brains=_v7_active_brains(); conn=db_connect(); now=datetime.now(UTC).isoformat(); evaluations=[]
    for brain in brains:
        result=_v7_evaluate_brain(brain,source); evaluations.append({'brain':brain,'result':result})
        conn.execute("""INSERT OR REPLACE INTO v7_brain_results
            (brain_key,horizon_hours,evaluated_at,trades,wins,losses,win_rate,profit_factor,expectancy_pct,
             expectancy_lower95_pct,max_drawdown_pct,research_score,eligible,accepted_decision_ids_json)
             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (brain['brain_key'],horizon,now,result['trades'],result['wins'],result['losses'],result['winRate'],
             result['profitFactor'],result['expectancyPct'],result['expectancyLower95Pct'],result['maxDrawdownPct'],
             result['researchScore'],1 if result['eligible'] else 0,json.dumps(result['acceptedDecisionIds'])))
        conn.execute("UPDATE v7_brains SET last_evaluated_at=? WHERE brain_key=?",(now,brain['brain_key']))
    evaluations.sort(key=lambda x:(x['result']['eligible'],x['result']['expectancyLower95Pct'],x['result']['researchScore'],x['result']['trades']),reverse=True)
    healthy=[x for x in evaluations if x['result']['eligible']]
    positive=[x for x in evaluations if x['result']['trades']>=V7_MIN_PARENT_SAMPLES and x['result']['expectancyPct']>0]
    parent_pool=healthy or positive
    discovery=None
    if not parent_pool:
        conn.commit(); conn.close(); discovery=v7_discover(horizon,child_count)
        return {'ok':True,'version':V7_VERSION,'advisoryOnly':True,'automaticLiveChanges':False,
                'horizonHours':horizon,'sourceObservations':len(source),'brainsEvaluated':len(evaluations),
                'generation':discovery.get('generation'),'childrenCreated':discovery.get('candidatesCreated',0),
                'brainsRetired':0,'champion':None,'researchChampion':_v7_public_eval(evaluations[0]) if evaluations else None,
                'discoveryFallback':True,'discovery':discovery,
                'note':'No profitable parent existed, so V7.1 generated evidence-driven candidates instead of mutating a losing champion.'}
    generation=max([int(x['brain'].get('generation') or 0) for x in evaluations] or [0])+1; created=[]
    for i in range(child_count):
        parent=parent_pool[i%len(parent_pool)]['brain']; cfg=_v7_mutate_config(parent['config'],i+1,generation)
        conn.execute("""INSERT OR IGNORE INTO v7_brains
            (brain_key,brain_name,generation,parent_key,status,created_at,config_json,origin)
            VALUES(?,?,?,?, 'ACTIVE',?,?,'mutation')""",(cfg['key'],cfg['name'],generation,parent['brain_key'],now,json.dumps(cfg,sort_keys=True)))
        created.append({'brainKey':cfg['key'],'brainName':cfg['name'],'parentKey':parent['brain_key'],'config':cfg})
    active_count=int(conn.execute("SELECT COUNT(*) FROM v7_brains WHERE status='ACTIVE'").fetchone()[0]); retired=[]
    if active_count>V7_POPULATION_LIMIT:
        removable=[x for x in reversed(evaluations) if x['brain']['origin']!='v6_seed']
        for item in removable[:active_count-V7_POPULATION_LIMIT]:
            key=item['brain']['brain_key']; conn.execute("UPDATE v7_brains SET status='RETIRED',retired_at=? WHERE brain_key=?",(now,key)); retired.append(key)
    champion=healthy[0] if healthy else None; research=evaluations[0] if evaluations else None
    payload={'ok':True,'version':V7_VERSION,'advisoryOnly':True,'automaticLiveChanges':False,'horizonHours':horizon,
             'sourceObservations':len(source),'brainsEvaluated':len(evaluations),'generation':generation,
             'childrenCreated':len(created),'brainsRetired':len(retired),'champion':_v7_public_eval(champion) if champion else None,
             'researchChampion':_v7_public_eval(research) if research else None,'children':created,'retiredBrainKeys':retired,
             'note':'Only eligible or positive-expectancy brains can parent mutations. No live setting changed.'}
    cur=conn.execute("""INSERT INTO v7_evolution_runs
        (created_at,completed_at,horizon_hours,parent_count,children_created,brains_retired,champion_key,payload_json)
        VALUES(?,?,?,?,?,?,?,?)""",(now,datetime.now(UTC).isoformat(),horizon,len(parent_pool),len(created),len(retired),
        champion['brain']['brain_key'] if champion else None,json.dumps(payload))); payload['runId']=int(cur.lastrowid)
    conn.commit(); conn.close(); return payload


def _v7_public_eval(item: Optional[Dict[str,Any]]) -> Optional[Dict[str,Any]]:
    if not item: return None
    return {'brainKey':item['brain']['brain_key'],'brainName':item['brain']['brain_name'],**item['result']}


def v7_brain_lab(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    _v7_ensure_tables(); horizon=max(1,int(horizon_hours)); conn=db_connect()
    rows=[dict(r) for r in conn.execute("""SELECT b.brain_key,b.brain_name,b.generation,b.parent_key,b.status,b.origin,b.created_at,
        r.trades,r.wins,r.losses,r.win_rate,r.profit_factor,r.expectancy_pct,r.expectancy_lower95_pct,
        r.max_drawdown_pct,r.research_score,r.eligible,b.config_json FROM v7_brains b
        LEFT JOIN v7_brain_results r ON r.brain_key=b.brain_key AND r.horizon_hours=?
        ORDER BY CASE WHEN b.status='ACTIVE' THEN 0 ELSE 1 END,COALESCE(r.eligible,0) DESC,
        COALESCE(r.expectancy_lower95_pct,-999) DESC,COALESCE(r.research_score,-999) DESC,b.generation DESC""",(horizon,)).fetchall()]
    last=conn.execute("SELECT payload_json FROM v7_evolution_runs ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
    for row in rows:
        try: row['config']=json.loads(row.pop('config_json'))
        except Exception: row['config']={}
        row['eligible']=bool(row.get('eligible') or 0)
    champion=next((x for x in rows if x['status']=='ACTIVE' and x['eligible']),None)
    research=next((x for x in rows if x['status']=='ACTIVE' and x.get('trades') is not None),None)
    return {'ok':True,'version':V7_VERSION,'advisoryOnly':True,'horizonHours':horizon,
            'activeBrains':sum(x['status']=='ACTIVE' for x in rows),'retiredBrains':sum(x['status']=='RETIRED' for x in rows),
            'champion':champion,'researchChampion':research,'brains':rows,
            'lastEvolutionRun':json.loads(last['payload_json']) if last and last['payload_json'] else None}


def v7_maintenance(trigger: str = 'manual', horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    _v7_ensure_tables(); started=datetime.now(UTC).isoformat(); conn=db_connect()
    cur=conn.execute("INSERT INTO v7_maintenance_runs(started_at,trigger) VALUES(?,?)",(started,str(trigger))); run_id=int(cur.lastrowid); conn.commit(); conn.close()
    repaired=errors=loops=0
    while loops<100:
        result=v6_repair_outcome_times(horizon_hours,V6_REPAIR_BATCH_SIZE); repaired+=int(result.get('repaired') or 0); errors+=int(result.get('errors') or 0); loops+=1
        if int(result.get('remaining') or 0)<=0: break
        time.sleep(.5)
    rebuild=v6_rebuild_validated(horizon_hours,V6_AUTO_SYNC_LIMIT)
    evolution=v7_evolve(horizon_hours,V7_CHILDREN_PER_RUN) if V7_AUTOMATIC_EVOLUTION else {'ok':True,'skipped':True}
    ok=bool(rebuild.get('ok')) and bool(evolution.get('ok')) and errors==0
    payload={'ok':ok,'version':V7_VERSION,'trigger':trigger,'repairLoops':loops,'repaired':repaired,'errors':errors,
             'remaining':0,'rebuild':rebuild,'evolution':evolution,'advisoryOnly':True,'automaticLiveChanges':False}
    conn=db_connect(); conn.execute("""UPDATE v7_maintenance_runs SET completed_at=?,repaired=?,errors=?,rebuild_json=?,evolution_json=?,ok=? WHERE id=?""",
        (datetime.now(UTC).isoformat(),repaired,errors,json.dumps(rebuild),json.dumps(evolution),1 if ok else 0,run_id)); conn.commit(); conn.close()
    payload['maintenanceRunId']=run_id; return payload


def v7_status_payload() -> Dict[str, Any]:
    lab=v7_brain_lab(V6_DEFAULT_HORIZON_HOURS); _v7_ensure_tables(); conn=db_connect()
    last=conn.execute("SELECT * FROM v7_maintenance_runs ORDER BY id DESC LIMIT 1").fetchone(); conn.close()
    now_uk=datetime.now(ZoneInfo('Europe/London')); days=(V7_WEEKEND_DAY-now_uk.weekday())%7
    next_run=(now_uk+timedelta(days=days)).replace(hour=V7_WEEKEND_HOUR_UK,minute=0,second=0,microsecond=0)
    if next_run<=now_uk: next_run+=timedelta(days=7)
    return {'ok':True,'version':V7_VERSION,'name':'Evidence-Driven Research Factory','enabled':V7_ENABLED,
            'advisoryOnly':True,'automaticLiveChanges':False,'automaticPromotion':False,
            'automaticEvolution':V7_AUTOMATIC_EVOLUTION,'weekendMaintenanceEnabled':V7_WEEKEND_MAINTENANCE_ENABLED,
            'nextWeekendMaintenanceAt':next_run.isoformat(),'populationLimit':V7_POPULATION_LIMIT,
            'childrenPerEvolution':V7_CHILDREN_PER_RUN,'activeBrains':lab.get('activeBrains',0),
            'retiredBrains':lab.get('retiredBrains',0),'champion':lab.get('champion'),
            'researchChampion':lab.get('researchChampion'),'lastMaintenance':dict(last) if last else None,
            'features':{'evidenceDrivenDiscovery':True,'winnerLoserAnalysis':True,'featureThresholdSearch':True,
                        'regimeAnalysis':True,'losingParentProtection':True,'mutationLineage':True,
                        'automaticRetirement':True,'shadowOnlyEvaluation':True,'humanApprovalRequired':True}}


def v7_weekend_worker() -> None:
    last_week_key=None
    while True:
        try:
            now=datetime.now(ZoneInfo('Europe/London')); week_key=f"{now.isocalendar().year}-{now.isocalendar().week}"
            if now.weekday()==V7_WEEKEND_DAY and now.hour>=V7_WEEKEND_HOUR_UK and week_key!=last_week_key:
                print(f"V7.1 WEEKEND RESEARCH | starting {now.isoformat()}"); result=v7_maintenance('weekend_scheduler',V6_DEFAULT_HORIZON_HOURS)
                last_week_key=week_key; print(f"V7.1 WEEKEND RESEARCH | ok={result.get('ok')} run={result.get('maintenanceRunId')}")
        except Exception as e: print(f"V7.1 WEEKEND WORKER ERROR: {e}")
        time.sleep(300)


@app.get('/v7/status')
def api_v7_status(): return v7_status_payload()

@app.get('/v7/brains')
def api_v7_brains(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS): return v7_brain_lab(horizon_hours)

@app.get('/v7/research/insights')
def api_v7_research_insights(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS): return v7_research_insights(horizon_hours)

@app.post('/v7/discover')
def api_v7_discover(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v7_discover(int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS),int(payload.get('candidates') or 12))

@app.post('/v7/evolve')
def api_v7_evolve(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v7_evolve(int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS),int(payload.get('children') or V7_CHILDREN_PER_RUN))

@app.post('/v7/maintenance')
def api_v7_maintenance(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v7_maintenance('manual',int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS))

print(f"TRADEBOT V2 | enabled={TRADEBOT_V2_ENABLED} mode={'paper' if PAPER else ('live' if TRADEBOT_V2_LIVE_ENABLED else 'validation-only')} min_samples={V2_MIN_SYMBOL_SAMPLES} min_pf={V2_MIN_PROFIT_FACTOR}")



# =========================
# TRADEBOT V8.0 — MARKET INTELLIGENCE ENGINE
# Shadow-only. This layer cannot alter live trading settings.
# =========================
V8_VERSION = "V8.0"
V8_NAME = "Market Intelligence Engine"
V8_POPULATION_LIMIT = int(os.getenv("V8_POPULATION_LIMIT", "30"))
V8_MIN_CONTEXT_SAMPLES = int(os.getenv("V8_MIN_CONTEXT_SAMPLES", "12"))


def _v8_ensure_tables() -> None:
    _v7_ensure_tables()
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v8_context_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        horizon_hours INTEGER NOT NULL,
        source_observations INTEGER NOT NULL DEFAULT 0,
        valid_observations INTEGER NOT NULL DEFAULT 0,
        candidates_created INTEGER NOT NULL DEFAULT 0,
        duplicates_skipped INTEGER NOT NULL DEFAULT 0,
        retired INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS v8_context_results (
        context_key TEXT NOT NULL,
        horizon_hours INTEGER NOT NULL,
        evaluated_at TEXT NOT NULL,
        trades INTEGER NOT NULL DEFAULT 0,
        wins INTEGER NOT NULL DEFAULT 0,
        losses INTEGER NOT NULL DEFAULT 0,
        win_rate REAL,
        profit_factor REAL,
        expectancy_pct REAL,
        expectancy_lower95_pct REAL,
        max_drawdown_pct REAL,
        context_score REAL,
        config_json TEXT NOT NULL,
        PRIMARY KEY(context_key, horizon_hours)
    )""")
    conn.commit(); conn.close()


def _v8_context_value(row: Dict[str, Any], key: str) -> Any:
    if key in ("spy_move", "qqq_move", "confidence", "quality", "momentum", "pullback", "spread"):
        try: return float(row.get(key) or 0.0)
        except Exception: return 0.0
    if key in ("hour_utc", "weekday", "position_count"):
        try: return int(row.get(key) or 0)
        except Exception: return 0
    return str(row.get(key) or "unknown").lower()


def _v8_context_accepts(row: Dict[str, Any], cfg: Dict[str, Any]) -> bool:
    # Existing stock-level gates remain available.
    if not _v6_accepts(row, cfg):
        return False
    spy = _v8_context_value(row, "spy_move")
    qqq = _v8_context_value(row, "qqq_move")
    hour = _v8_context_value(row, "hour_utc")
    weekday = _v8_context_value(row, "weekday")
    positions = _v8_context_value(row, "position_count")
    regime = _v8_context_value(row, "market_regime")
    session = _v8_context_value(row, "session_name")
    checks = (
        ("spy_min", spy, lambda a,b: a >= b), ("spy_max", spy, lambda a,b: a <= b),
        ("qqq_min", qqq, lambda a,b: a >= b), ("qqq_max", qqq, lambda a,b: a <= b),
        ("hour_min", hour, lambda a,b: a >= b), ("hour_max", hour, lambda a,b: a <= b),
        ("position_count_max", positions, lambda a,b: a <= b),
    )
    for name, value, fn in checks:
        if name in cfg and not fn(value, float(cfg[name])):
            return False
    if cfg.get("weekdays") and weekday not in {int(x) for x in cfg["weekdays"]}:
        return False
    if cfg.get("regimes") and regime not in {str(x).lower() for x in cfg["regimes"]}:
        return False
    if cfg.get("sessions") and session not in {str(x).lower() for x in cfg["sessions"]}:
        return False
    return True


def _v8_eval(rows: List[Dict[str, Any]], cfg: Dict[str, Any]) -> Dict[str, Any]:
    accepted=[{"decision_id":int(r.get("decision_id") or 0),
               "return_pct":float(r.get("net_return_pct") or 0.0)}
              for r in rows if _v8_context_accepts(r,cfg)]
    metrics=_v6_score_rows(accepted)
    eligible=(metrics["trades"] >= V7_MIN_PARENT_SAMPLES and
              metrics["profitFactor"] >= V6_RECOMMENDATION_MIN_PF and
              metrics["expectancyPct"] >= V6_RECOMMENDATION_MIN_EXPECTANCY and
              metrics["expectancyLower95Pct"] > 0)
    score=(_v6_research_score(metrics) if metrics["trades"] >= V6_MIN_SAMPLES else -999.0)
    return {**metrics,"eligible":eligible,"researchScore":score,
            "acceptedDecisionIds":[x["decision_id"] for x in accepted]}


def _v8_signature(cfg: Dict[str, Any]) -> str:
    ignored={"key","name","research_only","discovery_score","context_score"}
    clean={k:v for k,v in cfg.items() if k not in ignored}
    return json.dumps(clean,sort_keys=True,separators=(",",":"))


def v8_cleanup_population(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    _v8_ensure_tables(); horizon=max(1,int(horizon_hours)); rows=_v7_valid_rows(horizon)
    brains=_v7_active_brains(); evaluated=[]
    for brain in brains:
        result=_v8_eval(rows,brain.get("config") or {})
        evaluated.append({"brain":brain,"result":result,"signature":_v8_signature(brain.get("config") or {})})
    # Keep one copy per effective configuration. Prefer seed, then most trades, then score.
    groups={}
    for item in evaluated: groups.setdefault(item["signature"],[]).append(item)
    retire=[]
    for group in groups.values():
        group.sort(key=lambda x:(x["brain"].get("origin")=="v6_seed",x["result"]["trades"],x["result"]["researchScore"]),reverse=True)
        retire.extend(x["brain"]["brain_key"] for x in group[1:] if x["brain"].get("origin")!="v6_seed")
    survivors=[x for x in evaluated if x["brain"]["brain_key"] not in set(retire)]
    if len(survivors)>V8_POPULATION_LIMIT:
        removable=[x for x in survivors if x["brain"].get("origin")!="v6_seed"]
        removable.sort(key=lambda x:(x["result"]["eligible"],x["result"]["trades"]>0,x["result"]["researchScore"],x["result"]["expectancyPct"]))
        retire.extend(x["brain"]["brain_key"] for x in removable[:max(0,len(survivors)-V8_POPULATION_LIMIT)])
    retire=list(dict.fromkeys(retire)); now=datetime.now(UTC).isoformat()
    if retire:
        conn=db_connect()
        for key in retire: conn.execute("UPDATE v7_brains SET status='RETIRED',retired_at=? WHERE brain_key=? AND origin!='v6_seed'",(now,key))
        conn.commit(); conn.close()
    active=max(0,len(brains)-len(retire))
    return {"ok":True,"version":V8_VERSION,"populationLimit":V8_POPULATION_LIMIT,
            "activeBefore":len(brains),"retired":len(retire),"activeAfter":active,
            "retiredBrainKeys":retire,"duplicateProtection":True}


def _v8_market_context_candidates(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    if not rows: return []
    spy=[_v8_context_value(r,"spy_move") for r in rows]; qqq=[_v8_context_value(r,"qqq_move") for r in rows]
    spread=[_v8_context_value(r,"spread") for r in rows]; pull=[_v8_context_value(r,"pullback") for r in rows]
    hours=sorted(set(_v8_context_value(r,"hour_utc") for r in rows))
    sessions=sorted(set(_v8_context_value(r,"session_name") for r in rows))
    regimes=sorted(set(_v8_context_value(r,"market_regime") for r in rows))
    configs=[]
    # Broad market alignment and risk-off filters.
    for sm in sorted(set(round(_v7_quantile(spy,q),5) for q in (.2,.4,.6))):
        for qm in sorted(set(round(_v7_quantile(qqq,q),5) for q in (.2,.4,.6))):
            configs.append({"spy_min":sm,"qqq_min":qm,"max_spread":round(_v7_quantile(spread,.6),5)})
    # Session/time filters discovered from actual observations.
    for session in sessions:
        configs.append({"sessions":[session],"max_spread":round(_v7_quantile(spread,.6),5),"pullback_max":round(_v7_quantile(pull,.6),5)})
    if hours:
        for start in hours:
            for width in (1,2,3): configs.append({"hour_min":start,"hour_max":start+width,"spy_min":round(_v7_quantile(spy,.4),5)})
    for regime in regimes:
        if regime!="unknown": configs.append({"regimes":[regime],"spy_min":round(_v7_quantile(spy,.4),5),"qqq_min":round(_v7_quantile(qqq,.4),5)})
    # Low exposure contexts.
    configs.extend([{"position_count_max":0},{"position_count_max":1,"spy_min":round(_v7_quantile(spy,.4),5)}])
    scored=[]; seen=set()
    for cfg in configs:
        sig=_v8_signature(cfg)
        if sig in seen: continue
        seen.add(sig); result=_v8_eval(rows,cfg)
        if result["trades"]<V8_MIN_CONTEXT_SAMPLES: continue
        context_score=(result["expectancyPct"]*.45+result["expectancyLower95Pct"]*.30+
                       min(result["profitFactor"],3)*.20-result["maxDrawdownPct"]*.01)
        scored.append({"config":cfg,"backtest":result,"contextScore":context_score,"signature":sig})
    scored.sort(key=lambda x:(x["backtest"]["eligible"],x["contextScore"],x["backtest"]["expectancyPct"]),reverse=True)
    return scored[:max(1,min(limit,30))]


def v8_context_research(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS, candidates: int = 12) -> Dict[str, Any]:
    _v8_ensure_tables(); horizon=max(1,int(horizon_hours)); limit=max(1,min(int(candidates),30)); rows=_v7_valid_rows(horizon)
    found=_v8_market_context_candidates(rows,limit); conn=db_connect(); now=datetime.now(UTC).isoformat()
    existing={_v8_signature(json.loads(r[0])) for r in conn.execute("SELECT config_json FROM v7_brains").fetchall()}
    generation=int(conn.execute("SELECT COALESCE(MAX(generation),0)+1 FROM v7_brains").fetchone()[0]); created=[]; skipped=0
    for i,item in enumerate(found,1):
        if item["signature"] in existing: skipped+=1; continue
        cfg=dict(item["config"]); key=f"context_g{generation}_{secrets.token_hex(3)}"
        cfg.update({"key":key,"name":f"Market Context G{generation}.{i}","research_only":True,"context_score":round(item["contextScore"],6)})
        conn.execute("""INSERT INTO v7_brains(brain_key,brain_name,generation,parent_key,status,created_at,config_json,origin)
                     VALUES(?,?,?,NULL,'ACTIVE',?,?,'market_context')""",(key,cfg["name"],generation,now,json.dumps(cfg,sort_keys=True)))
        created.append({"brainKey":key,"brainName":cfg["name"],"config":cfg,"backtest":item["backtest"]})
        existing.add(item["signature"])
    conn.commit(); conn.close(); cleanup=v8_cleanup_population(horizon)
    healthy=sum(1 for x in created if x["backtest"].get("eligible"))
    payload={"ok":True,"version":V8_VERSION,"name":V8_NAME,"advisoryOnly":True,"automaticLiveChanges":False,
             "horizonHours":horizon,"validObservations":len(rows),"generation":generation,
             "candidatesCreated":len(created),"duplicatesSkipped":skipped,"healthyCandidates":healthy,
             "candidates":created,"populationCleanup":cleanup,
             "note":"Candidates use market context already captured at decision time. They remain shadow-only."}
    conn=db_connect(); cur=conn.execute("""INSERT INTO v8_context_runs(created_at,horizon_hours,source_observations,valid_observations,candidates_created,duplicates_skipped,retired,payload_json)
        VALUES(?,?,?,?,?,?,?,?)""",(now,horizon,len(_v6_source_rows(horizon,V6_AUTO_SYNC_LIMIT)),len(rows),len(created),skipped,cleanup["retired"],json.dumps(payload)))
    payload["runId"]=int(cur.lastrowid); conn.commit(); conn.close(); return payload


def v8_intelligence_report(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours)); rows=_v7_valid_rows(horizon)
    dimensions=("market_regime","session_name","weekday","hour_utc")
    report={}
    for dim in dimensions:
        groups={}
        for r in rows: groups.setdefault(str(_v8_context_value(r,dim)),[]).append(r)
        values=[]
        for key,group in groups.items():
            m=_v7_segment_metrics(group)
            if m["trades"]>=5: values.append({dim:key,**m})
        values.sort(key=lambda x:(x["expectancyPct"],x["profitFactor"],x["trades"]),reverse=True)
        report[dim]=values
    aligned=[r for r in rows if _v8_context_value(r,"spy_move")>=0 and _v8_context_value(r,"qqq_move")>=0]
    opposed=[r for r in rows if _v8_context_value(r,"spy_move")<0 or _v8_context_value(r,"qqq_move")<0]
    lab=v7_brain_lab(horizon)
    # Correct research champion: zero-trade brains are excluded.
    tested=[b for b in lab.get("brains",[]) if b.get("status")=="ACTIVE" and int(b.get("trades") or 0)>0]
    tested.sort(key=lambda b:(bool(b.get("eligible")),float(b.get("expectancy_lower95_pct") or -999),float(b.get("research_score") or -999)),reverse=True)
    return {"ok":True,"version":V8_VERSION,"name":V8_NAME,"advisoryOnly":True,"horizonHours":horizon,
            "validObservations":len(rows),"marketAlignment":{"bothNonNegative":_v7_segment_metrics(aligned),"riskOffOrDivergent":_v7_segment_metrics(opposed)},
            "contextBreakdown":report,"champion":next((b for b in tested if b.get("eligible")),None),
            "researchChampion":tested[0] if tested else None,"zeroTradeBrainsExcluded":True,
            "note":"This report uses only context recorded at the original decision timestamp."}


def v8_maintenance(trigger: str = "manual", horizon_hours: int = V6_DEFAULT_HORIZON_HOURS) -> Dict[str, Any]:
    horizon=max(1,int(horizon_hours)); repaired=errors=loops=0
    while loops<100:
        result=v6_repair_outcome_times(horizon,V6_REPAIR_BATCH_SIZE); repaired+=int(result.get("repaired") or 0); errors+=int(result.get("errors") or 0); loops+=1
        if int(result.get("remaining") or 0)<=0: break
    rebuild=v6_rebuild_validated(horizon,V6_AUTO_SYNC_LIMIT)
    research=v8_context_research(horizon,V7_CHILDREN_PER_RUN)
    return {"ok":bool(rebuild.get("ok")) and bool(research.get("ok")) and errors==0,"version":V8_VERSION,
            "trigger":trigger,"repairLoops":loops,"repaired":repaired,"errors":errors,"rebuild":rebuild,
            "marketIntelligence":research,"advisoryOnly":True,"automaticLiveChanges":False}


def v8_status_payload() -> Dict[str, Any]:
    _v8_ensure_tables(); intelligence=v8_intelligence_report(V6_DEFAULT_HORIZON_HOURS); lab=v7_brain_lab(V6_DEFAULT_HORIZON_HOURS)
    return {"ok":True,"version":V8_VERSION,"name":V8_NAME,"enabled":True,"advisoryOnly":True,
            "automaticLiveChanges":False,"automaticPromotion":False,"populationLimit":V8_POPULATION_LIMIT,
            "activeBrains":lab.get("activeBrains",0),"retiredBrains":lab.get("retiredBrains",0),
            "champion":intelligence.get("champion"),"researchChampion":intelligence.get("researchChampion"),
            "features":{"marketAlignment":True,"sessionIntelligence":True,"timeOfDayIntelligence":True,
                        "exposureContext":True,"zeroTradeChampionProtection":True,"duplicateCandidateProtection":True,
                        "hardPopulationLimit":True,"shadowOnlyEvaluation":True,"humanApprovalRequired":True}}


@app.get('/v8/status')
def api_v8_status(): return v8_status_payload()

@app.get('/v8/intelligence')
def api_v8_intelligence(horizon_hours: int = V6_DEFAULT_HORIZON_HOURS): return v8_intelligence_report(horizon_hours)

@app.post('/v8/research')
def api_v8_research(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v8_context_research(int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS),int(payload.get('candidates') or 12))

@app.post('/v8/cleanup')
def api_v8_cleanup(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v8_cleanup_population(int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS))

@app.post('/v8/maintenance')
def api_v8_maintenance(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v8_maintenance('manual',int(payload.get('horizonHours') or V6_DEFAULT_HORIZON_HOURS))


# =========================
# TRADEBOT V9.0 — MARKET MEMORY ENGINE
# Rich decision-time observations. Shadow-only and unable to alter live trading.
# =========================
V9_VERSION = "V9.1"
V9_NAME = "Live Market Intelligence Engine"
V9_ENABLED = os.getenv("V9_ENABLED", "true").lower() == "true"
V9_MIN_READY_OBSERVATIONS = max(100, int(os.getenv("V9_MIN_READY_OBSERVATIONS", "1000") or 1000))
V9_MIN_FIELD_COVERAGE = max(0.50, min(float(os.getenv("V9_MIN_FIELD_COVERAGE", "0.80") or 0.80), 1.0))


def _v9_ensure_tables() -> None:
    _v8_ensure_tables()
    if not SQLITE_ENABLED:
        return
    conn = db_connect()
    conn.execute("""CREATE TABLE IF NOT EXISTS v9_market_memory (
        decision_id INTEGER PRIMARY KEY,
        captured_at TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        symbol TEXT NOT NULL,
        decision TEXT,
        stage TEXT,
        reason TEXT,
        price REAL,
        confidence REAL,
        quality REAL,
        momentum REAL,
        pullback REAL,
        spread REAL,
        ready_to_buy INTEGER,
        sniper_pass INTEGER,
        a_plus_pass INTEGER,
        market_regime TEXT,
        session_name TEXT,
        weekday INTEGER,
        hour_utc INTEGER,
        spy_move REAL,
        qqq_move REAL,
        position_count INTEGER,
        relative_volume REAL,
        gap_pct REAL,
        distance_vwap_pct REAL,
        ema9_distance_pct REAL,
        ema20_distance_pct REAL,
        ema50_distance_pct REAL,
        atr_pct REAL,
        day_range_position REAL,
        opening_range_breakout INTEGER,
        premarket_volume REAL,
        sector TEXT,
        sector_strength REAL,
        news_score REAL,
        earnings_days INTEGER,
        float_shares REAL,
        shares_outstanding REAL,
        payload_json TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'live'
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v9_memory_symbol_time ON v9_market_memory(symbol, observed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_v9_memory_stage ON v9_market_memory(stage, decision)")
    conn.execute("""CREATE TABLE IF NOT EXISTS v9_memory_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        run_type TEXT NOT NULL,
        processed INTEGER NOT NULL DEFAULT 0,
        inserted INTEGER NOT NULL DEFAULT 0,
        updated INTEGER NOT NULL DEFAULT 0,
        errors INTEGER NOT NULL DEFAULT 0,
        payload_json TEXT
    )""")
    conn.commit(); conn.close()


def _v9_num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        x=float(value)
        return x if math.isfinite(x) else default
    except Exception:
        return default


def _v9_scan_value(scan: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in scan and scan.get(key) is not None:
            return scan.get(key)
    return default



# =========================
# V9.1 LIVE MARKET INTELLIGENCE COLLECTOR
# Shadow-only: enriches memory records and never changes order decisions.
# =========================
V91_INTELLIGENCE_ENABLED = os.getenv("V91_INTELLIGENCE_ENABLED", "true").lower() == "true"
V91_CACHE_SECONDS = max(30, int(os.getenv("V91_CACHE_SECONDS", "180") or 180))
_v91_cache: Dict[str, Dict[str, Any]] = {}
_v91_cache_lock = threading.Lock()

V91_SECTOR_MAP = {
    "AAPL":"Technology","MSFT":"Technology","NVDA":"Technology","AMD":"Technology","INTC":"Technology",
    "QCOM":"Technology","MU":"Technology","GOOG":"Communication Services","GOOGL":"Communication Services",
    "META":"Communication Services","AMZN":"Consumer Discretionary","TSLA":"Consumer Discretionary",
    "F":"Consumer Discretionary","GM":"Consumer Discretionary","HOOD":"Financials","SOFI":"Financials",
    "JPM":"Financials","BAC":"Financials","KO":"Consumer Staples","GIS":"Consumer Staples",
    "PPL":"Utilities","XOM":"Energy","CVX":"Energy","LLY":"Healthcare","PFE":"Healthcare",
    "PLTR":"Technology","LCID":"Consumer Discretionary","RIVN":"Consumer Discretionary","SNAP":"Communication Services",
}
V91_SECTOR_ETF = {
    "Technology":"XLK","Communication Services":"XLC","Consumer Discretionary":"XLY","Financials":"XLF",
    "Consumer Staples":"XLP","Utilities":"XLU","Energy":"XLE","Healthcare":"XLV","Industrials":"XLI",
    "Materials":"XLB","Real Estate":"XLRE",
}

def _v91_bars(symbol: str, timeframe: Any, start: datetime, end: datetime) -> List[Any]:
    req=StockBarsRequest(symbol_or_symbols=[symbol], timeframe=timeframe, start=start, end=end)
    response=data_client.get_stock_bars(req)
    try: return list(response[symbol])
    except Exception:
        data=getattr(response,"data",{}) or {}
        return list(data.get(symbol,[]))

def _v91_ema(values: List[float], period: int) -> Optional[float]:
    if not values: return None
    alpha=2.0/(period+1.0); value=float(values[0])
    for item in values[1:]: value=alpha*float(item)+(1.0-alpha)*value
    return value

def _v91_pct_distance(price: float, reference: Optional[float]) -> Optional[float]:
    return None if not reference or reference <= 0 else ((price/reference)-1.0)*100.0

def _v91_cached(symbol: str) -> Optional[Dict[str, Any]]:
    with _v91_cache_lock:
        item=_v91_cache.get(symbol)
        if item and time.time()-float(item.get("cached_at",0)) < V91_CACHE_SECONDS:
            return dict(item.get("data") or {})
    return None

def _v91_store_cache(symbol: str, data: Dict[str, Any]) -> None:
    with _v91_cache_lock: _v91_cache[symbol]={"cached_at":time.time(),"data":dict(data)}

def _v91_symbol_intelligence(symbol: str, price: float) -> Dict[str, Any]:
    sym=str(symbol).upper(); cached=_v91_cached(sym)
    if cached is not None: return cached
    result: Dict[str, Any]={}
    now=datetime.now(UTC)
    try:
        daily=_v91_bars(sym,TimeFrame.Day,now-timedelta(days=45),now)
        daily_rows=[]
        for b in daily:
            try: daily_rows.append({"o":float(b.open),"h":float(b.high),"l":float(b.low),"c":float(b.close),"v":float(b.volume or 0)})
            except Exception: pass
        if daily_rows:
            previous=daily_rows[-2] if len(daily_rows)>=2 else daily_rows[-1]
            today=daily_rows[-1]
            result["gap_pct"]=_v91_pct_distance(today["o"],previous["c"])
            trs=[]
            for i,row in enumerate(daily_rows[-15:]):
                prev_close=daily_rows[max(0,len(daily_rows)-15+i-1)]["c"]
                trs.append(max(row["h"]-row["l"],abs(row["h"]-prev_close),abs(row["l"]-prev_close)))
            atr=sum(trs)/len(trs) if trs else None
            result["atr_pct"]=(atr/price*100.0) if atr and price>0 else None
            avg_vol=sum(x["v"] for x in daily_rows[-21:-1])/max(1,len(daily_rows[-21:-1]))
            result["average_daily_volume"]=avg_vol
    except Exception as e: result["daily_error"]=str(e)[:160]
    try:
        et=ZoneInfo("America/New_York"); now_et=now.astimezone(et)
        session_open=now_et.replace(hour=9,minute=30,second=0,microsecond=0).astimezone(UTC)
        pre_open=now_et.replace(hour=4,minute=0,second=0,microsecond=0).astimezone(UTC)
        start=min(pre_open,now-timedelta(hours=14))
        bars=_v91_bars(sym,TimeFrame.Minute,start,now)
        rows=[]
        for b in bars:
            try: rows.append((b.timestamp,float(b.open),float(b.high),float(b.low),float(b.close),float(b.volume or 0)))
            except Exception: pass
        if rows:
            closes=[x[4] for x in rows]; volumes=[x[5] for x in rows]
            typical=[(x[2]+x[3]+x[4])/3.0 for x in rows]
            total_volume=sum(volumes); pv=sum(t*v for t,v in zip(typical,volumes)); vwap=pv/total_volume if total_volume>0 else None
            result["distance_vwap_pct"]=_v91_pct_distance(price,vwap)
            result["ema9_distance_pct"]=_v91_pct_distance(price,_v91_ema(closes,9))
            result["ema20_distance_pct"]=_v91_pct_distance(price,_v91_ema(closes,20))
            result["ema50_distance_pct"]=_v91_pct_distance(price,_v91_ema(closes,50))
            high=max(x[2] for x in rows); low=min(x[3] for x in rows)
            result["day_range_position"]=(price-low)/(high-low) if high>low else 0.5
            elapsed=max(1.0,min(390.0,(now-session_open).total_seconds()/60.0)); fraction=max(1/390,elapsed/390.0)
            avg_daily=float(result.get("average_daily_volume") or 0.0)
            result["relative_volume"]=(total_volume/(avg_daily*fraction)) if avg_daily>0 else None
            result["premarket_volume"]=sum(x[5] for x in rows if _v6_parse_utc(x[0]) < session_open)
            orb_end=session_open+timedelta(minutes=30)
            orb=[x for x in rows if session_open <= _v6_parse_utc(x[0]) <= orb_end]
            result["opening_range_breakout"]=bool(orb and price > max(x[2] for x in orb))
            result["current_volume"]=total_volume
    except Exception as e: result["intraday_error"]=str(e)[:160]
    sector=V91_SECTOR_MAP.get(sym,"unknown"); result["sector"]=sector
    _v91_store_cache(sym,result); return result

def _v91_market_context() -> Dict[str, Any]:
    cached=_v91_cached("__MARKET__")
    if cached is not None: return cached
    context: Dict[str, Any]={}
    moves=[]
    for symbol in ("SPY","QQQ"):
        try:
            q=get_quote(symbol); intel=_v91_symbol_intelligence(symbol,float(q["mid"]))
            move=(intel.get("gap_pct") or 0.0)+(intel.get("distance_vwap_pct") or 0.0)
            context[f"{symbol.lower()}_move_pct"]=move; moves.append(move)
            context[f"{symbol.lower()}_above_vwap"]=(intel.get("distance_vwap_pct") or 0.0)>0
        except Exception: pass
    avg=sum(moves)/len(moves) if moves else 0.0
    both_above=bool(context.get("spy_above_vwap") and context.get("qqq_above_vwap"))
    both_below=bool(context.get("spy_above_vwap") is False and context.get("qqq_above_vwap") is False)
    if avg>=1.0 and both_above: regime="STRONG_RISK_ON"
    elif avg>=0.2 and both_above: regime="RISK_ON"
    elif avg<=-1.0 and both_below: regime="STRONG_RISK_OFF"
    elif avg<=-0.2 and both_below: regime="RISK_OFF"
    elif abs(avg)<0.25: regime="SIDEWAYS"
    else: regime="MIXED"
    context["market_regime"]=regime
    _v91_store_cache("__MARKET__",context); return context

def _v91_enrich_scan(scan: Dict[str, Any]) -> Dict[str, Any]:
    if not V91_INTELLIGENCE_ENABLED: return scan
    symbol=str(scan.get("symbol") or "").upper(); price=float(scan.get("price") or 0.0)
    if not symbol or price<=0: return scan
    enriched=dict(scan)
    try: enriched.update({k:v for k,v in _v91_symbol_intelligence(symbol,price).items() if v is not None})
    except Exception as e: enriched["v91_symbol_error"]=str(e)[:160]
    try:
        market=_v91_market_context(); enriched["market_regime"]=market.get("market_regime","UNKNOWN")
        if market.get("spy_move_pct") is not None: enriched["spy_move"]=float(market["spy_move_pct"])/100.0
        if market.get("qqq_move_pct") is not None: enriched["qqq_move"]=float(market["qqq_move_pct"])/100.0
    except Exception as e: enriched["v91_market_error"]=str(e)[:160]
    sector=enriched.get("sector")
    etf=V91_SECTOR_ETF.get(str(sector))
    if etf:
        try:
            q=get_quote(etf); si=_v91_symbol_intelligence(etf,float(q["mid"]))
            enriched["sector_strength"]=(si.get("gap_pct") or 0.0)+(si.get("distance_vwap_pct") or 0.0)
        except Exception: pass
    return enriched

def _v9_capture_snapshot(conn, decision_id: int, scan: Dict[str, Any], decision: str,
                         stage: str, reason: str, observed_at: datetime, source: str = "live") -> None:
    symbol=str(scan.get("symbol") or "").upper().strip()
    if not symbol or decision_id <= 0:
        return
    if source == "live":
        scan = _v91_enrich_scan(scan)
    dna=conn.execute("SELECT market_regime,session_name,weekday,hour_utc,spy_move,qqq_move,position_count FROM v4_market_dna WHERE decision_id=?",(decision_id,)).fetchone()
    if dna:
        regime,session,weekday,hour,spy,qqq,positions=dna
        regime=scan.get("market_regime") or regime
        spy=scan.get("spy_move") if scan.get("spy_move") is not None else spy
        qqq=scan.get("qqq_move") if scan.get("qqq_move") is not None else qqq
    else:
        regime=_v4_market_regime(); session=_v4_session_name(observed_at); weekday=observed_at.weekday(); hour=observed_at.hour
        spy=_v4_index_move("SPY"); qqq=_v4_index_move("QQQ")
        try: positions=len(trading_client.get_all_positions())
        except Exception: positions=0
    payload={
        "schemaVersion":1,
        "explanation":{
            "decision":str(decision),"stage":str(stage),"reason":str(reason)[:1000],
            "sniperReason":scan.get("sniper_reason"),"aPlusReason":scan.get("a_plus_reason")
        },
        "rawScan":{k:v for k,v in scan.items() if isinstance(v,(str,int,float,bool,type(None)))}
    }
    fields={
        "relative_volume":_v9_num(_v9_scan_value(scan,"relative_volume","rvol","relativeVolume")),
        "gap_pct":_v9_num(_v9_scan_value(scan,"gap_pct","gap_percent","gapPercent")),
        "distance_vwap_pct":_v9_num(_v9_scan_value(scan,"distance_vwap_pct","vwap_distance_pct","distanceFromVwapPct")),
        "ema9_distance_pct":_v9_num(_v9_scan_value(scan,"ema9_distance_pct","ema9DistancePct")),
        "ema20_distance_pct":_v9_num(_v9_scan_value(scan,"ema20_distance_pct","ema20DistancePct")),
        "ema50_distance_pct":_v9_num(_v9_scan_value(scan,"ema50_distance_pct","ema50DistancePct")),
        "atr_pct":_v9_num(_v9_scan_value(scan,"atr_pct","atrPercent")),
        "day_range_position":_v9_num(_v9_scan_value(scan,"day_range_position","range_position","dayRangePosition")),
        "opening_range_breakout":int(bool(_v9_scan_value(scan,"opening_range_breakout","orb","openingRangeBreakout",default=False))),
        "premarket_volume":_v9_num(_v9_scan_value(scan,"premarket_volume","premarketVolume")),
        "sector":str(_v9_scan_value(scan,"sector",default="unknown") or "unknown"),
        "sector_strength":_v9_num(_v9_scan_value(scan,"sector_strength","sectorStrength")),
        "news_score":_v9_num(_v9_scan_value(scan,"news_score","newsScore")),
        "earnings_days":int(_v9_num(_v9_scan_value(scan,"earnings_days","days_to_earnings","earningsDays"),999) or 999),
        "float_shares":_v9_num(_v9_scan_value(scan,"float_shares","float","floatShares")),
        "shares_outstanding":_v9_num(_v9_scan_value(scan,"shares_outstanding","sharesOutstanding")),
    }
    conn.execute("""INSERT OR REPLACE INTO v9_market_memory(
        decision_id,captured_at,observed_at,symbol,decision,stage,reason,price,confidence,quality,momentum,pullback,spread,
        ready_to_buy,sniper_pass,a_plus_pass,market_regime,session_name,weekday,hour_utc,spy_move,qqq_move,position_count,
        relative_volume,gap_pct,distance_vwap_pct,ema9_distance_pct,ema20_distance_pct,ema50_distance_pct,atr_pct,
        day_range_position,opening_range_breakout,premarket_volume,sector,sector_strength,news_score,earnings_days,
        float_shares,shares_outstanding,payload_json,source)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (decision_id,datetime.now(UTC).isoformat(),observed_at.isoformat(),symbol,str(decision),str(stage),str(reason)[:1000],
         _v9_num(scan.get("price"),0.0),_v9_num(scan.get("confidence"),0.0),_v9_num(scan.get("quality_score"),0.0),
         _v9_num(scan.get("short_momentum"),0.0),_v9_num(scan.get("pullback"),0.0),_v9_num(scan.get("spread"),0.0),
         int(bool(scan.get("ready_to_buy"))),int(bool(scan.get("sniper_pass"))),int(bool(scan.get("a_plus_pass"))),
         str(regime or "unknown"),str(session or "unknown"),int(weekday or 0),int(hour or 0),_v9_num(spy,0.0),_v9_num(qqq,0.0),int(positions or 0),
         fields["relative_volume"],fields["gap_pct"],fields["distance_vwap_pct"],fields["ema9_distance_pct"],fields["ema20_distance_pct"],
         fields["ema50_distance_pct"],fields["atr_pct"],fields["day_range_position"],fields["opening_range_breakout"],fields["premarket_volume"],
         fields["sector"],fields["sector_strength"],fields["news_score"],fields["earnings_days"],fields["float_shares"],fields["shares_outstanding"],
         json.dumps(payload,default=str),str(source)))


def v9_backfill(limit: int = 5000) -> Dict[str, Any]:
    _v9_ensure_tables(); limit=max(1,min(int(limit),50000)); processed=inserted=errors=0
    conn=db_connect()
    rows=conn.execute("""SELECT d.id,d.timestamp,d.symbol,d.decision,d.stage,d.reason,d.price,d.confidence,d.quality,d.momentum,d.pullback,d.spread,
        d.ready_to_buy,d.sniper_pass,d.a_plus_pass,d.payload_json
        FROM v2_setup_decisions d LEFT JOIN v9_market_memory m ON m.decision_id=d.id
        WHERE m.decision_id IS NULL ORDER BY d.id ASC LIMIT ?""",(limit,)).fetchall()
    for row in rows:
        processed+=1
        try:
            (did,ts,symbol,decision,stage,reason,price,confidence,quality,momentum,pullback,spread,ready,sniper,a_plus,payload_json)=row
            try: observed=datetime.fromisoformat(str(ts).replace("Z","+00:00"))
            except Exception: observed=datetime.now(UTC)
            scan={"symbol":symbol,"price":price,"confidence":confidence,"quality_score":quality,"short_momentum":momentum,
                  "pullback":pullback,"spread":spread,"ready_to_buy":bool(ready),"sniper_pass":bool(sniper),"a_plus_pass":bool(a_plus)}
            try:
                payload=json.loads(payload_json or "{}")
                if isinstance(payload,dict):
                    scan.update({k:v for k,v in payload.items() if k not in scan})
            except Exception: pass
            _v9_capture_snapshot(conn,int(did),scan,str(decision),str(stage),str(reason),observed,"historical_backfill")
            inserted+=1
        except Exception as e:
            errors+=1; print(f"V9 BACKFILL ERROR: {e}")
    now=datetime.now(UTC).isoformat(); payload={"ok":errors==0,"version":V9_VERSION,"processed":processed,"inserted":inserted,"errors":errors}
    cur=conn.execute("INSERT INTO v9_memory_runs(created_at,run_type,processed,inserted,updated,errors,payload_json) VALUES(?,?,?,?,?,?,?)",
                     (now,"backfill",processed,inserted,0,errors,json.dumps(payload)))
    payload["runId"]=int(cur.lastrowid); conn.commit(); conn.close(); return payload


def v9_coverage() -> Dict[str, Any]:
    _v9_ensure_tables(); conn=db_connect(); total=int(conn.execute("SELECT COUNT(*) FROM v9_market_memory").fetchone()[0])
    fields=["market_regime","spy_move","qqq_move","relative_volume","gap_pct","distance_vwap_pct","ema9_distance_pct","ema20_distance_pct",
            "ema50_distance_pct","atr_pct","day_range_position","premarket_volume","sector","sector_strength","news_score","float_shares"]
    coverage={}
    for f in fields:
        if f in ("market_regime","sector"):
            present=int(conn.execute(f"SELECT COUNT(*) FROM v9_market_memory WHERE {f} IS NOT NULL AND lower({f}) NOT IN ('','unknown')").fetchone()[0])
        else:
            present=int(conn.execute(f"SELECT COUNT(*) FROM v9_market_memory WHERE {f} IS NOT NULL").fetchone()[0])
        coverage[f]={"present":present,"coverage":round(present/total,4) if total else 0.0}
    live=int(conn.execute("SELECT COUNT(*) FROM v9_market_memory WHERE source='live'").fetchone()[0]); backfilled=total-live
    decisions=int(conn.execute("SELECT COUNT(*) FROM v2_setup_decisions").fetchone()[0]); conn.close()
    rich=[coverage[f]["coverage"] for f in fields if f not in ("market_regime","spy_move","qqq_move")]
    rich_avg=sum(rich)/len(rich) if rich else 0.0
    ready=total>=V9_MIN_READY_OBSERVATIONS and rich_avg>=V9_MIN_FIELD_COVERAGE
    return {"ok":True,"version":V9_VERSION,"totalSnapshots":total,"liveSnapshots":live,"backfilledSnapshots":backfilled,
            "sourceDecisions":decisions,"missingSnapshots":max(0,decisions-total),"fieldCoverage":coverage,
            "richFieldAverageCoverage":round(rich_avg,4),"v10Ready":ready,
            "requirements":{"minimumSnapshots":V9_MIN_READY_OBSERVATIONS,"minimumRichFieldCoverage":V9_MIN_FIELD_COVERAGE}}


def v9_recent_memory(limit: int = 50) -> Dict[str, Any]:
    _v9_ensure_tables(); limit=max(1,min(int(limit),500)); conn=db_connect()
    cols=[x[1] for x in conn.execute("PRAGMA table_info(v9_market_memory)").fetchall()]
    rows=conn.execute("SELECT * FROM v9_market_memory ORDER BY decision_id DESC LIMIT ?",(limit,)).fetchall(); conn.close()
    items=[]
    for row in rows:
        d=dict(zip(cols,row)); d.pop("payload_json",None); items.append(d)
    return {"ok":True,"version":V9_VERSION,"count":len(items),"items":items}


def v9_status_payload() -> Dict[str, Any]:
    cov=v9_coverage()
    return {"ok":True,"version":V9_VERSION,"name":V9_NAME,"enabled":V9_ENABLED,"advisoryOnly":True,
            "automaticLiveChanges":False,"automaticPromotion":False,"snapshots":cov["totalSnapshots"],
            "liveSnapshots":cov["liveSnapshots"],"missingSnapshots":cov["missingSnapshots"],"v10Ready":cov["v10Ready"],
            "features":{"automaticDecisionSnapshots":True,"historicalBackfill":True,"explainableDecisionMemory":True,
                        "marketContext":True,"technicalFeatureSchema":True,"newsAndFundamentalPlaceholders":True,
                        "coverageMonitoring":True,"liveTechnicalCollection":V91_INTELLIGENCE_ENABLED,"marketRegimeDetection":True,
                        "relativeVolume":True,"vwapAndEmaDistances":True,"atrAndGap":True,"sectorContext":True,"shadowOnly":True}}


@app.get('/v9/status')
def api_v9_status(): return v9_status_payload()

@app.get('/v9/coverage')
def api_v9_coverage(): return v9_coverage()

@app.get('/v9/memory')
def api_v9_memory(limit: int = 50): return v9_recent_memory(limit)

@app.post('/v9/backfill')
def api_v9_backfill(request: Request, payload: Dict[str, Any] = Body(default={})):
    verify_api_key(request); return v9_backfill(int(payload.get('limit') or 5000))


@app.get('/v9/intelligence/{symbol}')
def api_v9_intelligence(symbol: str, request: Request):
    verify_api_key(request)
    sym=str(symbol or '').upper().strip()
    if not re.fullmatch(r'[A-Z.\-]{1,10}',sym):
        raise HTTPException(status_code=400,detail='Invalid symbol')
    quote=get_quote(sym)
    scan={'symbol':sym,'price':quote['mid'],'bid':quote['bid'],'ask':quote['ask'],'spread':quote['spread']}
    enriched=_v91_enrich_scan(scan)
    return {'ok':True,'version':V9_VERSION,'symbol':sym,'intelligence':enriched}
