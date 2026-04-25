
import os
import json
import time
import math
import re
import threading
from datetime import datetime, UTC, timedelta
from typing import Dict, Any, List, Optional

import requests
from fastapi import FastAPI, Request, HTTPException
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
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY")

PAPER = os.getenv("PAPER", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing APCA_API_KEY_ID or APCA_API_SECRET_KEY")


# =========================
# CORE CONFIG
# =========================
BOT_NAME = "Rebuilt Sniper Profit Bot"

SAFE_UNIVERSE = [
    "SOFI", "PLTR", "F", "RIVN", "LCID", "AAL", "NIO", "PLUG", "OPEN", "PFE", "T",
    "NVDA", "MSFT", "AAPL", "GOOGL", "AMZN", "META", "AVGO", "AMD", "XOM"
]

CHECK_INTERVAL = 60
UNIVERSE_REFRESH_SECONDS = 60 * 30

MAX_POSITIONS = 12
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

TRADE_HISTORY_FILE = "trade_history.json"
STOCK_MEMORY_FILE = "stock_memory.json"


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
equity_curve: List[Dict[str, Any]] = []

bot_enabled = True
manual_override = False
emergency_stop = False
bot_thread_started = False
bot_lock = threading.Lock()

starting_equity_today: Optional[float] = None
starting_equity_day: Optional[str] = None
last_rotation_ts = 0


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
                "pnl": pnl,
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
    item = {**event, "timestamp": datetime.now(UTC).isoformat(), "equity": equity}
    trade_history.append(item)
    if len(trade_history) > 2000:
        del trade_history[:-2000]
    save_trade_history()


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
    target_value = equity * TARGET_POSITION_VALUE_PCT
    max_value = equity * MAX_POSITION_VALUE_PCT
    usable_cash = max(0.0, buying_power - CASH_BUFFER)
    return round(max(0.0, min(target_value, max_value, usable_cash)), 2)


def confidence_notional(scan):
    base = calculate_new_position_notional()
    if not CONFIDENCE_SIZING_ENABLED:
        return base
    confidence, label = calculate_confidence(scan)
    mult = HIGH_CONFIDENCE_SIZE_MULTIPLIER if label == "HIGH" else MEDIUM_CONFIDENCE_SIZE_MULTIPLIER if label == "MEDIUM" else LOW_CONFIDENCE_SIZE_MULTIPLIER
    try:
        equity = float(get_account().equity)
    except Exception:
        equity = 0.0
    cap = equity * MAX_CONFIDENCE_POSITION_VALUE_PCT if equity > 0 else base
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
    event = {"day": today_str(), "time": now_time(), "side": "BUY", "symbol": symbol, "amount": round(notional_amount, 2), "reason": reason, "pnl": 0.0}
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
    event = {"day": today_str(), "time": now_time(), "side": "SELL", "symbol": symbol, "qty": rounded_qty, "reason": reason, "pnl": round(pnl, 4), "pnlPct": round(pnl_pct, 4)}
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
# STRATEGY
# =========================
def refresh_universe_if_needed(force=False):
    global current_universe, last_universe_refresh_ts
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
        price = p["price"]
        entry = p["entry"]
        qty = p["qty"]
        highest = p["highest"]
        if price <= 0 or entry <= 0:
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

        trail_start_price = entry * TRAIL_START
        if price >= trail_start_price and highest is not None:
            trail_floor = highest * TRAIL_GIVEBACK
            if price <= trail_floor:
                try:
                    if pdt_aware_should_avoid_sell(symbol, "MONEY MODE TRAILING PROFIT", p["pnlPct"]):
                        continue
                    market_sell_qty(symbol, qty, entry=entry, price=price, reason="MONEY MODE TRAILING PROFIT")
                    state[symbol]["highest_since_entry"] = None
                except Exception as e:
                    print(f"SELL ERROR {symbol}: {e}")


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
# STATUS
# =========================
def update_equity_curve(account):
    point = {"t": now_chart_time(), "value": float(account.equity)}
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
        "mode": "SNIPER_CONFIDENCE_MEMORY_TIMELINE",
        "market": market_status,
        "strictOneCyclePerStockPerDay": STRICT_ONE_CYCLE_PER_STOCK_PER_DAY,
        "allowCustomBuy": ALLOW_CUSTOM_BUY,
        "profitModeEnabled": PROFIT_MODE_ENABLED,
        "rotationModeEnabled": ROTATION_MODE_ENABLED,
        "pdtAwareModeEnabled": PDT_AWARE_MODE_ENABLED,
        "sniperModeEnabled": SNIPER_MODE_ENABLED,
        "confidenceSizingEnabled": CONFIDENCE_SIZING_ENABLED,
        "stockMemoryEnabled": STOCK_MEMORY_ENABLED,
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
            "sniperMinConfidence": SNIPER_MIN_CONFIDENCE,
            "sniperMinQuality": SNIPER_MIN_QUALITY,
        },
        "account": {
            "equity": float(account.equity),
            "buyingPower": float(account.buying_power),
            "cash": float(account.cash),
            "pnlDay": float(daily_pnl),
        },
        "activePosition": {
            "symbol": active["symbol"] if active else "—",
            "qty": float(active["qty"]) if active else 0.0,
            "entry": float(active["entry"]) if active else 0.0,
            "price": float(active["price"]) if active else 0.0,
            "pnl": float(active["pnl"]) if active else 0.0,
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
            } for s in scans
        ],
        "logs": [
            f"MODE | SNIPER_CONFIDENCE_MEMORY_TIMELINE | max_positions={MAX_POSITIONS} | allowed_new={allowed_new_position_count()}",
            f"SNIPER | enabled={SNIPER_MODE_ENABLED} | confidence_sizing={CONFIDENCE_SIZING_ENABLED} | memory={STOCK_MEMORY_ENABLED} | timeline={len(trade_history)}",
            f"A+ GATE | enabled={A_PLUS_GATE_ENABLED} | min_conf={A_PLUS_MIN_CONFIDENCE} | min_quality={A_PLUS_MIN_QUALITY} | blacklist={len(temp_blacklist)}",
            f"PDT AWARE | enabled={PDT_AWARE_MODE_ENABLED} | today_buys={today_buy_count()}/{MAX_NEW_BUYS_PER_DAY_PDT_AWARE} | warnings={len(pdt_warning_events)}",
            f"MARKET | {market_status.get('label', 'UNKNOWN')}",
            f"ACCOUNT | equity={float(account.equity):.2f} | buying_power={float(account.buying_power):.2f}",
            f"POSITIONS | {len(positions)}",
            f"LOCKOUT | locked_today={', '.join(locked_symbols) if locked_symbols else 'none'}",
        ],
        "trades": trade_events[-50:],
        "tradeTimeline": trade_history[-1000:],
        "stockMemory": stock_memory_payload(),
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
@app.get("/")
def root():
    return {"message": "Rebuilt Sniper Profit Bot running", "status": "/status", "paperMode": PAPER}


@app.get("/status")
def get_status():
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


# =========================
# LOOP
# =========================
def run_bot_loop():
    print("Rebuilt Sniper Profit Bot started...")
    load_persistent_state()
    refresh_universe_if_needed(force=True)
    reset_daily_flags_if_needed()
    update_status(BOT_NAME, [])

    while True:
        try:
            with bot_lock:
                reset_daily_flags_if_needed()
                cleanup_temp_blacklist()
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
