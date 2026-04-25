
import os
import json
import time
import threading
from datetime import datetime, UTC
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
# MONEY MODE BOT + STRICT LOCKOUT + CUSTOM BUY
# ============================================================
# Rule:
# BUY stock -> HOLD stock -> SELL stock -> LOCK stock until tomorrow.
#
# Custom Buy:
# - POST /custom-buy/{symbol}
# - Buys a ticker even if it was not originally hardcoded.
# - Adds it to the active managed universe.
# - Then stop loss + trailing profit manage it like any other bot stock.
#
# Important:
# - Lockout blocks RE-BUYS only.
# - Lockout does NOT block selling a position you already hold.
# ============================================================


# =========================
# ENV / CONFIG
# =========================
API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY")

PAPER = os.getenv("PAPER", "false").lower() == "true"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BOT_NAME = "Money Mode strict-lockout custom-buy bot"

SAFE_UNIVERSE = [
    "SOFI",
    "PLTR",
    "F",
    "RIVN",
    "LCID",
    "AAL",
    "NIO",
    "PLUG",
    "OPEN",
    "PFE",
    "T",
]

CHECK_INTERVAL = 60
UNIVERSE_REFRESH_SECONDS = 60 * 30

# Strict daily lockout
STRICT_ONE_CYCLE_PER_STOCK_PER_DAY = True

# Custom buy safety
ALLOW_CUSTOM_BUY = True
CUSTOM_BUY_REQUIRES_MARKET_OPEN = True

# Profit mode upgrade
PROFIT_MODE_ENABLED = True
ROTATION_MODE_ENABLED = True
ROTATION_MIN_QUALITY_EDGE = 0.018
ROTATE_ONLY_IF_WEAKEST_PNL_BELOW = 0.35
ROTATION_COOLDOWN_SECONDS = 60 * 20
MIN_BUY_QUALITY_SCORE = 0.018
MIN_BUY_SHORT_MOMENTUM = -0.004
PREFER_POSITIVE_MOMENTUM = True
PAUSE_NEW_BUYS_IF_DAILY_PNL_BELOW = -3.00

# PDT-aware safety upgrade
PDT_AWARE_MODE_ENABLED = True

# If a position was bought today, avoid normal/profit sells that may be rejected by Alpaca PDT.
# Emergency sell and hard stop-loss can still try to sell.
AVOID_SAME_DAY_PROFIT_SELLS = True
AVOID_SAME_DAY_ROTATION_SELLS = True

# Slower/safer mode: avoid flipping quickly.
MIN_HOLD_MINUTES_BEFORE_PROFIT_SELL = 45
MIN_HOLD_MINUTES_BEFORE_ROTATION = 60

# Hard stop-loss override. If loss is worse than this, still attempt sell even if bought today.
HARD_STOP_LOSS_PCT = -3.50

# Buy fewer stocks quickly to avoid creating many same-day exit traps.
MAX_NEW_BUYS_PER_DAY_PDT_AWARE = 6

# Sniper + confidence + memory upgrade
SNIPER_MODE_ENABLED = True
CONFIDENCE_SIZING_ENABLED = True
STOCK_MEMORY_ENABLED = True
TRADE_TIMELINE_ENABLED = True

TRADE_HISTORY_FILE = "trade_history.json"
STOCK_MEMORY_FILE = "stock_memory.json"

SNIPER_MIN_CONFIDENCE = 0.58
SNIPER_MIN_QUALITY = 0.020
SNIPER_MAX_SPREAD = 0.012
SNIPER_MIN_PULLBACK = 0.0015
SNIPER_MAX_PULLBACK = 0.035
SNIPER_MIN_MOMENTUM = -0.003

LOW_CONFIDENCE_SIZE_MULTIPLIER = 0.65
MEDIUM_CONFIDENCE_SIZE_MULTIPLIER = 1.00
HIGH_CONFIDENCE_SIZE_MULTIPLIER = 1.35
MAX_CONFIDENCE_POSITION_VALUE_PCT = 0.14

MEMORY_MIN_TRADES_FOR_TRUST = 3
MEMORY_BAD_WINRATE = 0.35
MEMORY_GOOD_WINRATE = 0.58
MEMORY_BAD_MULTIPLIER = 0.70
MEMORY_GOOD_MULTIPLIER = 1.15



# Money mode risk
MAX_POSITIONS = 4
MAX_NEW_BUYS_PER_LOOP = 1
MAX_POSITION_VALUE_PCT = 0.30
TARGET_POSITION_VALUE_PCT = 0.22
MIN_ORDER_NOTIONAL = 1.00
CASH_BUFFER = 0.50

# Liquidity/spread protection
MAX_SPREAD = 0.015
PREFER_SPREAD_UNDER = 0.006

# Entry logic
BUY_DIP = 0.9985
MIN_PULLBACK = 0.0010
MAX_PULLBACK = 0.0450
MIN_TICKS_BEFORE_BUY = 3

# Momentum behaviour
MOMENTUM_LOOKBACK_POINTS = 5
MIN_SHORT_MOMENTUM = -0.015
MAX_SHORT_MOMENTUM = 0.045

# Exits
STOP_LOSS = 0.982
TRAIL_START = 1.012
TRAIL_GIVEBACK = 0.993

# Daily safety
MAX_DAILY_LOSS = -8.00
MAX_TRADES_PER_DAY = 12

DUST_THRESHOLD = 0.1

SYNC_ALL_ALPACA_POSITIONS = True
MANAGE_OUTSIDE_UNIVERSE_POSITIONS = False

ENABLE_MANUAL_BUTTONS = True


# =========================
# CLIENTS
# =========================
if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing APCA_API_KEY_ID or APCA_API_SECRET_KEY")

trading_client = TradingClient(API_KEY, API_SECRET, paper=PAPER)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)


# =========================
# STATE
# =========================
current_universe = list(SAFE_UNIVERSE)

state: Dict[str, Dict[str, Any]] = {}

for symbol in current_universe:
    state[symbol] = {
        "ref": None,
        "highest_since_entry": None,
        "price_curve": [],
        "last_seen_price": None,
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
alpaca_rejection_events: List[Dict[str, Any]] = []
pdt_warning_events: List[Dict[str, Any]] = []
equity_curve: List[Dict[str, Any]] = []

bot_enabled = True
manual_override = False
emergency_stop = False
last_rotation_ts = 0

starting_equity_today: Optional[float] = None
starting_equity_day: Optional[str] = None

bot_thread_started = False
bot_lock = threading.Lock()



# =========================
# DASHBOARD API KEY SECURITY
# =========================
def verify_api_key(request: Request):
    if not DASHBOARD_API_KEY:
        raise HTTPException(status_code=500, detail="Dashboard API key not configured")

    key = request.headers.get("x-api-key")

    if key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")


# =========================
# FASTAPI
# =========================
app = FastAPI(title="Money Mode Custom Buy Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "message": "Money Mode custom-buy backend running",
        "status": "/status",
        "manual_buy": "/manual-buy",
        "custom_buy": "/custom-buy/{symbol}",
        "manual_sell": "/manual-sell",
        "sell_symbol": "/sell/{symbol}",
        "emergency_sell": "/emergency-sell",
        "pause": "/pause",
        "resume": "/resume",
        "manual_override_on": "/manual-override/on",
        "manual_override_off": "/manual-override/off",
        "paperMode": PAPER,
        "strictLockout": STRICT_ONE_CYCLE_PER_STOCK_PER_DAY,
        "allowCustomBuy": ALLOW_CUSTOM_BUY,
        "profitModeEnabled": PROFIT_MODE_ENABLED,
        "rotationModeEnabled": ROTATION_MODE_ENABLED,
        "rotationCooldownSeconds": ROTATION_COOLDOWN_SECONDS,
        "minBuyQualityScore": MIN_BUY_QUALITY_SCORE,
        "rotationMinQualityEdge": ROTATION_MIN_QUALITY_EDGE,
        "pdtAwareModeEnabled": PDT_AWARE_MODE_ENABLED,
        "pdtWarningEvents": pdt_warning_events[-50:],
        "todayBuyCount": today_buy_count(),
        "maxNewBuysPerDayPdtAware": MAX_NEW_BUYS_PER_DAY_PDT_AWARE,
    }


@app.get("/status")
def get_status():
    return latest_status


@app.post("/pause")
def pause_bot(request: Request):
    verify_api_key(request)
    global bot_enabled
    bot_enabled = False
    notify("⏸️ Strict Lockout Money Mode paused")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot paused"}


@app.post("/resume")
def resume_bot(request: Request):
    verify_api_key(request)
    global bot_enabled, emergency_stop
    bot_enabled = True
    emergency_stop = False
last_rotation_ts = 0
    notify("▶️ Strict Lockout Money Mode resumed")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot resumed"}


@app.post("/manual-override/on")
def manual_override_on(request: Request):
    verify_api_key(request)
    global manual_override
    manual_override = True
    notify("🟠 Manual override ON. Auto-buy paused.")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Manual override ON. Auto-buy paused."}


@app.post("/manual-override/off")
def manual_override_off(request: Request):
    verify_api_key(request)
    global manual_override
    manual_override = False
    notify("🟢 Manual override OFF. Auto-buy active.")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Manual override OFF. Auto-buy active."}


@app.post("/manual-buy")
def manual_buy(request: Request):
    verify_api_key(request)
    if not ENABLE_MANUAL_BUTTONS:
        return {"ok": False, "message": "Manual buttons disabled"}

    try:
        with bot_lock:
            clock = trading_client.get_clock()

            if not clock.is_open:
                return {"ok": False, "message": "Market closed"}

            if emergency_stop:
                return {"ok": False, "message": "Emergency stop is active"}

            if not latest_scans:
                return {"ok": False, "message": "No scan data yet"}

            result = money_mode_buy(latest_scans, manual=True)
            update_status(BOT_NAME, latest_scans)

            return {"ok": True, "message": result or "Manual money-mode buy attempted"}

    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/custom-buy/{symbol}")
def custom_buy(symbol: str, request: Request):
    verify_api_key(request)
    if not ENABLE_MANUAL_BUTTONS or not ALLOW_CUSTOM_BUY:
        return {"ok": False, "message": "Custom buy disabled"}

    try:
        with bot_lock:
            result = buy_custom_symbol(symbol.upper().strip())
            update_status(BOT_NAME, latest_scans)
            return result

    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/manual-sell")
def manual_sell(request: Request):
    verify_api_key(request)
    if not ENABLE_MANUAL_BUTTONS:
        return {"ok": False, "message": "Manual buttons disabled"}

    try:
        with bot_lock:
            result = close_worst_or_largest_position(reason="MANUAL SELL")
            update_status(BOT_NAME, latest_scans)
            return result

    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/sell/{symbol}")
def sell_symbol(symbol: str, request: Request):
    verify_api_key(request)
    if not ENABLE_MANUAL_BUTTONS:
        return {"ok": False, "message": "Manual buttons disabled"}

    try:
        with bot_lock:
            result = close_position_by_symbol(symbol.upper(), reason="MANUAL SYMBOL SELL")
            update_status(BOT_NAME, latest_scans)
            return result

    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/emergency-sell")
def emergency_sell(request: Request):
    verify_api_key(request)
    global emergency_stop, bot_enabled

    try:
        with bot_lock:
            emergency_stop = True
            bot_enabled = False
            result = close_all_positions(reason="EMERGENCY SELL")
            notify("🚨 Emergency sell all activated")
            update_status(BOT_NAME, latest_scans)
            return {
                **result,
                "emergencyStop": True,
                "botEnabled": False,
            }

    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.on_event("startup")
def startup_event():
    global bot_thread_started

    if bot_thread_started:
        return

    load_persistent_state()
    bot_thread_started = True
    thread = threading.Thread(target=run_bot_loop, daemon=True)
    thread.start()



# =========================
# TRADE HISTORY / STOCK MEMORY
# =========================
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
    global trade_history, stock_memory
    trade_history = safe_load_json(TRADE_HISTORY_FILE, [])
    stock_memory = safe_load_json(STOCK_MEMORY_FILE, {})


def save_trade_history():
    safe_save_json(TRADE_HISTORY_FILE, trade_history[-2000:])


def save_stock_memory():
    safe_save_json(STOCK_MEMORY_FILE, stock_memory)


def get_memory(symbol: str):
    symbol = symbol.upper()
    if symbol not in stock_memory:
        stock_memory[symbol] = {
            "wins": 0,
            "losses": 0,
            "trades": 0,
            "totalPnl": 0.0,
            "totalPnlPct": 0.0,
            "avgPnl": 0.0,
            "avgPnlPct": 0.0,
            "winRate": 0.0,
            "trust": "NEW",
            "lastResult": "—",
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

    account_equity = 0.0
    try:
        account_equity = float(get_account().equity)
    except Exception:
        pass

    timeline_event = {
        **event,
        "timestamp": datetime.now(UTC).isoformat(),
        "equity": account_equity,
    }

    trade_history.append(timeline_event)

    if len(trade_history) > 2000:
        del trade_history[:-2000]

    save_trade_history()


def calculate_confidence(scan: Dict[str, Any]):
    quality = float(scan.get("quality_score", 0.0))
    spread = float(scan.get("spread", 1.0))
    momentum = float(scan.get("short_momentum", 0.0))
    pullback = float(scan.get("pullback", 0.0))
    symbol = scan.get("symbol", "")

    confidence = 0.0

    confidence += min(0.35, quality * 8.0)

    if spread <= PREFER_SPREAD_UNDER:
        confidence += 0.20
    elif spread <= MAX_SPREAD:
        confidence += 0.10

    if momentum >= 0:
        confidence += 0.20
    elif momentum >= SNIPER_MIN_MOMENTUM:
        confidence += 0.10

    if SNIPER_MIN_PULLBACK <= pullback <= SNIPER_MAX_PULLBACK:
        confidence += 0.15

    confidence *= memory_multiplier(symbol)
    confidence = max(0.0, min(1.0, confidence))

    if confidence >= 0.75:
        label = "HIGH"
    elif confidence >= 0.58:
        label = "MEDIUM"
    else:
        label = "LOW"

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


def confidence_notional(scan: Dict[str, Any]):
    base = calculate_new_position_notional()
    if not CONFIDENCE_SIZING_ENABLED:
        return base

    confidence, label = calculate_confidence(scan)

    if label == "HIGH":
        mult = HIGH_CONFIDENCE_SIZE_MULTIPLIER
    elif label == "MEDIUM":
        mult = MEDIUM_CONFIDENCE_SIZE_MULTIPLIER
    else:
        mult = LOW_CONFIDENCE_SIZE_MULTIPLIER

    try:
        equity = float(get_account().equity)
    except Exception:
        equity = 0.0

    max_conf_value = equity * MAX_CONFIDENCE_POSITION_VALUE_PCT if equity > 0 else base
    adjusted = min(base * mult, max_conf_value)

    return round(max(0.0, adjusted), 2)


def trade_timeline_payload():
    return trade_history[-1000:]


def stock_memory_payload():
    items = []
    for symbol, m in stock_memory.items():
        items.append({"symbol": symbol, **m})
    items.sort(key=lambda x: (x.get("trust") != "GOOD", -x.get("winRate", 0), -x.get("trades", 0)))
    return items


# =========================
# TIME / NOTIFY
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
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=5,
        )
    except Exception:
        pass


def ensure_symbol_state(symbol: str, custom=False):
    if symbol not in state:
        state[symbol] = {
            "ref": None,
            "highest_since_entry": None,
            "price_curve": [],
            "last_seen_price": None,
            "custom": custom,
        }

    if custom:
        state[symbol]["custom"] = True


def add_symbol_to_universe(symbol: str, custom=False):
    global current_universe

    symbol = symbol.upper().strip()

    if symbol not in current_universe:
        current_universe.append(symbol)

    ensure_symbol_state(symbol, custom=custom)

    if custom:
        custom_symbols[symbol] = True


def reset_daily_flags_if_needed():
    global starting_equity_today, starting_equity_day

    today = today_str()

    stale_locked = [symbol for symbol, day in locked_today.items() if day != today]
    for symbol in stale_locked:
        del locked_today[symbol]

    if starting_equity_day != today:
        try:
            account = trading_client.get_account()
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
        return {
            "isOpen": False,
            "timestamp": "",
            "nextOpen": "",
            "nextClose": "",
            "label": "UNKNOWN",
            "error": str(e),
        }


# =========================
# MARKET / ACCOUNT
# =========================
def get_quote(symbol: str):
    req = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    quote = data_client.get_stock_latest_quote(req)[symbol]

    bid = quote.bid_price
    ask = quote.ask_price

    if bid is None or ask is None or bid <= 0 or ask <= 0:
        raise ValueError(f"Bad quote for {symbol}")

    mid = (bid + ask) / 2.0
    spread = (ask - bid) / mid

    return {
        "bid": float(bid),
        "ask": float(ask),
        "mid": float(mid),
        "spread": float(spread),
    }


def get_position(symbol: str):
    try:
        pos = trading_client.get_open_position(symbol)
        return float(pos.qty), float(pos.avg_entry_price)
    except Exception:
        return 0.0, 0.0


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

            positions.append(
                {
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
                }
            )

        except Exception:
            continue

    positions.sort(key=lambda p: abs(p.get("marketValue", 0.0)), reverse=True)
    return positions


def get_open_orders(symbol=None):
    try:
        request = GetOrdersRequest(status=QueryOrderStatus.OPEN)
        orders = trading_client.get_orders(filter=request)

        if symbol is None:
            return orders

        return [order for order in orders if order.symbol == symbol]

    except Exception:
        return []


def has_open_order(symbol: str):
    return len(get_open_orders(symbol)) > 0


def get_account():
    return trading_client.get_account()


def get_buying_power():
    account = get_account()
    return float(account.buying_power)


def get_equity():
    account = get_account()
    return float(account.equity)


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



# =========================
# ALPACA REJECTION / PDT NOTIFICATIONS
# =========================
def is_likely_pdt_error(error_text: str):
    lower = str(error_text).lower()
    pdt_terms = [
        "pattern day",
        "pdt",
        "day trade",
        "day-trade",
        "daytrading",
        "day trading",
    ]
    return any(term in lower for term in pdt_terms)


def add_alpaca_rejection_event(symbol: str, reason: str, error_text: str):
    is_pdt = is_likely_pdt_error(error_text)
    label = "PDT BLOCK" if is_pdt else "ALPACA SELL REJECTED"

    event = {
        "day": today_str(),
        "time": now_time(),
        "symbol": symbol,
        "type": label,
        "reason": reason,
        "message": f"{label} | {symbol} sell was rejected by Alpaca.",
        "error": str(error_text),
    }

    alpaca_rejection_events.append(event)

    if len(alpaca_rejection_events) > 100:
        alpaca_rejection_events.pop(0)

    print(f"{event['message']} | {event['error']}")
    notify(f"⚠️ {event['message']} Reason: {event['error']}")



# =========================
# SELL RELIABILITY HELPERS
# =========================
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


# =========================
# ORDERS
# =========================
def market_buy_notional(symbol: str, notional_amount: float, reason="AUTO BUY"):
    order = MarketOrderRequest(
        symbol=symbol,
        notional=round(notional_amount, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )

    trading_client.submit_order(order)

    event = {
        "day": today_str(),
        "time": now_time(),
        "side": "BUY",
        "symbol": symbol,
        "amount": round(notional_amount, 2),
        "reason": reason,
        "pnl": 0.0,
    }

    trade_events.append(event)
    add_trade_history_event(event)
    notify(f"🟢 {reason}: ${round(notional_amount, 2)} {symbol}")

    if len(trade_events) > 200:
        trade_events.pop(0)


def market_sell_qty(symbol: str, qty: float, entry: float = 0.0, price: float = 0.0, reason="AUTO SELL"):
    # SELL RELIABILITY MODE:
    # Floors quantity so we never request slightly more than Alpaca says is available.
    requested_qty = float(qty)
    rounded_qty = floor_qty(requested_qty, 6)

    if rounded_qty <= 0:
        return

    order = MarketOrderRequest(
        symbol=symbol,
        qty=rounded_qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )

    try:
        trading_client.submit_order(order)
    except Exception as e:
        err_text = str(e)

        if is_insufficient_qty_error(err_text):
            available_qty = parse_available_qty(err_text)

            if available_qty is not None:
                retry_qty = floor_qty(available_qty, 6)

                if retry_qty > 0 and retry_qty < rounded_qty:
                    retry_order = MarketOrderRequest(
                        symbol=symbol,
                        qty=retry_qty,
                        side=OrderSide.SELL,
                        time_in_force=TimeInForce.DAY,
                    )

                    try:
                        trading_client.submit_order(retry_order)
                        rounded_qty = retry_qty
                    except Exception as retry_error:
                        add_alpaca_rejection_event(symbol, reason, f"Initial: {err_text} | Retry: {retry_error}")
                        raise
                else:
                    add_alpaca_rejection_event(symbol, reason, err_text)
                    raise
            else:
                add_alpaca_rejection_event(symbol, reason, err_text)
                raise
        else:
            add_alpaca_rejection_event(symbol, reason, err_text)
            raise

    estimated_pnl = 0.0
    estimated_pnl_pct = 0.0

    if entry > 0 and price > 0:
        estimated_pnl = (price - entry) * rounded_qty
        estimated_pnl_pct = ((price / entry) - 1.0) * 100.0

    event = {
        "day": today_str(),
        "time": now_time(),
        "side": "SELL",
        "symbol": symbol,
        "qty": rounded_qty,
        "reason": reason,
        "pnl": round(estimated_pnl, 4),
        "pnlPct": round(estimated_pnl_pct, 4),
    }

    trade_events.append(event)
    add_trade_history_event(event)
    update_stock_memory_from_sell(symbol, estimated_pnl, estimated_pnl_pct)
    notify(f"🔴 {reason}: {symbol} | qty={rounded_qty} | est PnL {round(estimated_pnl, 4)} ({round(estimated_pnl_pct, 2)}%)")

    lock_symbol_until_tomorrow(symbol)

    if len(trade_events) > 200:
        trade_events.pop(0)


def close_position(position: Dict[str, Any], reason="MANUAL SELL"):
    symbol = position["symbol"]
    qty = position["qty"]
    entry = position["entry"]
    price = position["price"]

    if not symbol or qty <= DUST_THRESHOLD:
        return {"ok": False, "message": "No open position to sell"}

    if has_open_order(symbol):
        return {"ok": False, "message": f"{symbol} already has open order"}

    market_sell_qty(symbol, qty, entry=entry, price=price, reason=reason)

    if symbol in state:
        state[symbol]["highest_since_entry"] = None

    return {
        "ok": True,
        "message": f"{reason} submitted for {symbol}. {symbol} locked until tomorrow.",
        "symbol": symbol,
        "qty": qty,
        "entry": entry,
        "price": price,
    }


def close_position_by_symbol(symbol: str, reason="MANUAL SYMBOL SELL"):
    positions = get_all_positions()

    for position in positions:
        if position["symbol"] == symbol:
            return close_position(position, reason=reason)

    return {"ok": False, "message": f"No open position found for {symbol}"}


def close_worst_or_largest_position(reason="MANUAL SELL"):
    positions = get_all_positions()

    if not positions:
        return {"ok": False, "message": "No open position to sell"}

    positions.sort(key=lambda p: (p["pnlPct"], -abs(p["marketValue"])))
    return close_position(positions[0], reason=reason)


def close_all_positions(reason="EMERGENCY SELL"):
    positions = get_all_positions()

    if not positions:
        return {"ok": False, "message": "No open positions to sell"}

    results = []

    for position in positions:
        if has_open_order(position["symbol"]):
            results.append(
                {
                    "symbol": position["symbol"],
                    "ok": False,
                    "message": "Existing open order",
                }
            )
            continue

        try:
            result = close_position(position, reason=reason)
            results.append(result)
        except Exception as e:
            results.append(
                {
                    "symbol": position["symbol"],
                    "ok": False,
                    "message": str(e),
                }
            )

    return {
        "ok": True,
        "message": f"{reason} attempted for {len(positions)} positions. Sold symbols locked until tomorrow.",
        "results": results,
    }


# =========================
# UNIVERSE / SCAN
# =========================
def refresh_universe_if_needed(force=False):
    global current_universe, last_universe_refresh_ts

    now = time.time()

    if not force and (now - last_universe_refresh_ts) < UNIVERSE_REFRESH_SECONDS:
        return

    # Keep custom symbols even when base universe refreshes.
    new_universe = list(SAFE_UNIVERSE)

    for symbol in custom_symbols.keys():
        if symbol not in new_universe:
            new_universe.append(symbol)

    current_universe = new_universe

    for symbol in current_universe:
        ensure_symbol_state(symbol, custom=symbol in custom_symbols)

    last_universe_refresh_ts = now
    print(f"CUSTOM BUY STRICT LOCKOUT UNIVERSE REFRESHED: {', '.join(current_universe)}")


def compute_short_momentum(symbol: str, current_price: float):
    curve = state[symbol].get("price_curve", [])

    if len(curve) < MOMENTUM_LOOKBACK_POINTS:
        return 0.0

    old = curve[-MOMENTUM_LOOKBACK_POINTS]["value"]

    if old <= 0:
        return 0.0

    return (current_price / old) - 1.0


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
        not locked
        and price <= buy_trigger
        and spread <= MAX_SPREAD
        and MIN_PULLBACK <= pullback <= MAX_PULLBACK
        and short_momentum >= MIN_SHORT_MOMENTUM
        and len(curve) >= MIN_TICKS_BEFORE_BUY
    )

    score = (price / ref) - 1.0 if ref > 0 else 0.0

    return {
        "symbol": symbol,
        "price": price,
        "spread": spread,
        "bid": quote["bid"],
        "ask": quote["ask"],
        "qty": qty,
        "entry": entry,
        "ref": ref,
        "score": score,
        "pullback": pullback,
        "short_momentum": short_momentum,
        "quality_score": quality_score,
        "buy_trigger": buy_trigger,
        "ready_to_buy": ready_to_buy,
        "locked_today": locked,
        "custom": symbol in custom_symbols,
        "highest_since_entry": state[symbol].get("highest_since_entry"),
        "price_curve": curve,
        "confidence": calculate_confidence({"symbol": symbol, "quality_score": quality_score, "spread": spread, "short_momentum": short_momentum, "pullback": pullback})[0],
        "confidence_label": calculate_confidence({"symbol": symbol, "quality_score": quality_score, "spread": spread, "short_momentum": short_momentum, "pullback": pullback})[1],
        "sniper_pass": sniper_passes({"symbol": symbol, "quality_score": quality_score, "spread": spread, "short_momentum": short_momentum, "pullback": pullback})[0],
        "sniper_reason": sniper_passes({"symbol": symbol, "quality_score": quality_score, "spread": spread, "short_momentum": short_momentum, "pullback": pullback})[1],
    }


def can_buy_symbol(symbol: str):
    if STRICT_ONE_CYCLE_PER_STOCK_PER_DAY and is_locked_today(symbol):
        return False, f"{symbol} locked until tomorrow"

    if has_open_order(symbol):
        return False, f"{symbol} existing open order"

    qty, _ = get_position(symbol)

    if qty > DUST_THRESHOLD:
        return False, f"{symbol} already holding"

    return True, ""



def get_best_profit_candidate(scans):
    candidates = []

    for scan in scans:
        symbol = scan["symbol"]

        can_buy, reason = can_buy_symbol(symbol)
        if not can_buy:
            continue

        if scan["spread"] > MAX_SPREAD:
            continue

        if scan["quality_score"] < MIN_BUY_QUALITY_SCORE:
            continue

        if scan["short_momentum"] < MIN_BUY_SHORT_MOMENTUM:
            continue

        if PREFER_POSITIVE_MOMENTUM and scan["short_momentum"] < 0:
            continue

        if SNIPER_MODE_ENABLED:
            sniper_ok, sniper_reason = sniper_passes(scan)
            if not sniper_ok:
                print(f"SNIPER SKIP {symbol} | {sniper_reason}")
                continue

        if PROFIT_MODE_ENABLED:
            if scan["quality_score"] < MIN_BUY_QUALITY_SCORE:
                continue

            if scan["short_momentum"] < MIN_BUY_SHORT_MOMENTUM:
                continue

            if PREFER_POSITIVE_MOMENTUM and scan["short_momentum"] < 0:
                continue

            if get_daily_pnl() <= PAUSE_NEW_BUYS_IF_DAILY_PNL_BELOW:
                continue

            if PDT_AWARE_MODE_ENABLED and today_buy_count() >= MAX_NEW_BUYS_PER_DAY_PDT_AWARE:
                continue

        if not scan["ready_to_buy"]:
            continue

        candidates.append(scan)

    candidates.sort(key=lambda x: (-x["quality_score"], -x["short_momentum"], x["spread"]))
    return candidates[0] if candidates else None


def get_weakest_position_for_rotation():
    positions = get_all_positions()
    managed = [p for p in positions if p["symbol"] in current_universe]

    if not managed:
        return None

    managed.sort(key=lambda p: (p["pnlPct"], p.get("spread", 0.0), -abs(p.get("marketValue", 0.0))))
    return managed[0]


def can_rotate_now():
    if not PROFIT_MODE_ENABLED or not ROTATION_MODE_ENABLED:
        return False, "rotation disabled"

    if emergency_stop:
        return False, "emergency stop active"

    if manual_override:
        return False, "manual override active"

    if time.time() - last_rotation_ts < ROTATION_COOLDOWN_SECONDS:
        return False, "rotation cooldown active"

    blocked, reason = risk_blocked()
    if blocked:
        return False, reason

    daily_pnl = get_daily_pnl()
    if daily_pnl <= PAUSE_NEW_BUYS_IF_DAILY_PNL_BELOW:
        return False, f"daily pnl below buy threshold: {daily_pnl:.2f}"

    return True, ""


def maybe_rotate_weakest_into_best(scans):
    global last_rotation_ts

    allowed, reason = can_rotate_now()
    if not allowed:
        return f"ROTATION SKIP | {reason}"

    best = get_best_profit_candidate(scans)
    if not best:
        return "ROTATION SKIP | no strong candidate"

    weakest = get_weakest_position_for_rotation()
    if not weakest:
        return "ROTATION SKIP | no position to rotate"

    if weakest["symbol"] == best["symbol"]:
        return "ROTATION SKIP | best candidate already held"

    if weakest["pnlPct"] > ROTATE_ONLY_IF_WEAKEST_PNL_BELOW:
        return f"ROTATION SKIP | weakest {weakest['symbol']} still acceptable pnl={weakest['pnlPct']:.2f}%"

    quality_edge = best["quality_score"] - max(0.0, weakest["pnlPct"] / 100.0)

    if quality_edge < ROTATION_MIN_QUALITY_EDGE:
        return f"ROTATION SKIP | edge too small best={best['symbol']} edge={quality_edge:.4f}"

    try:
        if pdt_aware_should_avoid_sell(weakest["symbol"], f"PROFIT MODE ROTATE OUT FOR {best['symbol']}", weakest["pnlPct"], allow_hard_stop=False):
            return f"ROTATION SKIP | PDT-aware hold for {weakest['symbol']} until next day reset"

        sell_result = close_position(weakest, reason=f"PROFIT MODE ROTATE OUT FOR {best['symbol']}")

        if not sell_result.get("ok"):
            return f"ROTATION SELL BLOCKED | {sell_result.get('message', 'unknown')}"

        time.sleep(2)

        notional = calculate_new_position_notional()

        if notional < MIN_ORDER_NOTIONAL:
            return f"ROTATION BUY SKIP | not enough usable cash after sell: {notional:.2f}"

        market_buy_notional(best["symbol"], notional, reason=f"PROFIT MODE ROTATE INTO FROM {weakest['symbol']}")
        state[best["symbol"]]["ref"] = best["price"]
        state[best["symbol"]]["highest_since_entry"] = best["price"]
        last_rotation_ts = time.time()

        return f"ROTATION DONE | sold {weakest['symbol']} -> bought {best['symbol']} ${notional:.2f}"

    except Exception as e:
        return f"ROTATION ERROR | {e}"


def pick_money_mode_stocks(scans):
    candidates = []

    for scan in scans:
        symbol = scan["symbol"]

        can_buy, reason = can_buy_symbol(symbol)
        if not can_buy:
            print(f"SKIP BUY {symbol} | {reason}")
            continue

        if scan["spread"] > MAX_SPREAD:
            print(f"SKIP BUY {symbol} | spread too wide: {scan['spread']:.4f}")
            continue

        if SNIPER_MODE_ENABLED:
            sniper_ok, sniper_reason = sniper_passes(scan)
            if not sniper_ok:
                print(f"SNIPER SKIP {symbol} | {sniper_reason}")
                continue

        if PROFIT_MODE_ENABLED:
            if scan["quality_score"] < MIN_BUY_QUALITY_SCORE:
                continue

            if scan["short_momentum"] < MIN_BUY_SHORT_MOMENTUM:
                continue

            if PREFER_POSITIVE_MOMENTUM and scan["short_momentum"] < 0:
                continue

            if get_daily_pnl() <= PAUSE_NEW_BUYS_IF_DAILY_PNL_BELOW:
                continue

            if PDT_AWARE_MODE_ENABLED and today_buy_count() >= MAX_NEW_BUYS_PER_DAY_PDT_AWARE:
                continue

        if not scan["ready_to_buy"]:
            continue

        candidates.append(scan)

    candidates.sort(key=lambda x: (-x["quality_score"], x["spread"]))
    return candidates



# =========================
# PDT-AWARE HELPERS
# =========================
def get_today_buy_event(symbol: str):
    today = today_str()
    for event in reversed(trade_events):
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
        now = datetime.now(UTC)
        return max(0, int((now - buy_time).total_seconds() / 60))
    except Exception:
        return 0


def today_buy_count():
    today = today_str()
    return len([t for t in trade_events if t.get("side") == "BUY" and t.get("day") == today])


def add_pdt_warning(symbol: str, reason: str):
    event = {
        "day": today_str(),
        "time": now_time(),
        "symbol": symbol,
        "reason": reason,
        "message": f"PDT AWARE | {symbol}: {reason}",
    }

    if pdt_warning_events:
        last = pdt_warning_events[-1]
        if last.get("symbol") == symbol and last.get("reason") == reason and last.get("day") == today_str():
            return

    pdt_warning_events.append(event)

    if len(pdt_warning_events) > 100:
        pdt_warning_events.pop(0)

    print(event["message"])


def pdt_aware_should_avoid_sell(symbol: str, reason: str, pnl_pct: float, allow_hard_stop: bool = False):
    if not PDT_AWARE_MODE_ENABLED:
        return False

    if not was_bought_today(symbol):
        return False

    # Hard stop loss still attempts to sell.
    if allow_hard_stop and pnl_pct <= HARD_STOP_LOSS_PCT:
        add_pdt_warning(symbol, f"hard stop override: attempting sell despite same-day buy, pnl={pnl_pct:.2f}%")
        return False

    mins = minutes_since_today_buy(symbol)

    if "ROTATE" in reason.upper():
        if AVOID_SAME_DAY_ROTATION_SELLS:
            add_pdt_warning(symbol, f"rotation skipped because {symbol} was bought today; hold until next day reset")
            return True

        if mins < MIN_HOLD_MINUTES_BEFORE_ROTATION:
            add_pdt_warning(symbol, f"rotation skipped; held only {mins} mins, minimum {MIN_HOLD_MINUTES_BEFORE_ROTATION}")
            return True

    if "TRAILING" in reason.upper() or "PROFIT" in reason.upper():
        if AVOID_SAME_DAY_PROFIT_SELLS:
            add_pdt_warning(symbol, f"profit sell skipped because {symbol} was bought today; hold until next day reset")
            return True

        if mins < MIN_HOLD_MINUTES_BEFORE_PROFIT_SELL:
            add_pdt_warning(symbol, f"profit sell skipped; held only {mins} mins, minimum {MIN_HOLD_MINUTES_BEFORE_PROFIT_SELL}")
            return True

    return False

# =========================
# POSITION MANAGEMENT
# =========================
def can_manage_position(position: Dict[str, Any]):
    symbol = position["symbol"]

    if not MANAGE_OUTSIDE_UNIVERSE_POSITIONS and symbol not in current_universe:
        return False, f"{symbol} outside universe"

    if has_open_order(symbol):
        return False, f"{symbol} existing open order"

    return True, ""


def manage_money_mode_positions():
    positions = get_all_positions()

    for position in positions:
        symbol = position["symbol"]
        qty = position["qty"]
        entry = position["entry"]
        price = position["price"]
        highest = position["highest"]

        allowed, reason = can_manage_position(position)
        if not allowed:
            print(f"SKIP SELL {symbol} | {reason}")
            continue

        if price <= 0 or entry <= 0:
            continue

        stop_price = entry * STOP_LOSS

        if price <= stop_price:
            try:
                if pdt_aware_should_avoid_sell(symbol, "MONEY MODE STOP LOSS", position["pnlPct"], allow_hard_stop=True):
                    continue
                market_sell_qty(symbol, qty, entry=entry, price=price, reason="MONEY MODE STOP LOSS")
                state[symbol]["highest_since_entry"] = None
                print(f"MONEY MODE STOP LOSS SELL {qty:.6f} {symbol} | locked until tomorrow")
            except Exception as e:
                print(f"SELL ERROR {symbol}: {e}")

            continue

        trail_start_price = entry * TRAIL_START

        if price >= trail_start_price and highest is not None:
            trail_floor = highest * TRAIL_GIVEBACK

            if price <= trail_floor:
                try:
                    if pdt_aware_should_avoid_sell(symbol, "MONEY MODE TRAILING PROFIT", position["pnlPct"], allow_hard_stop=False):
                        continue
                    market_sell_qty(symbol, qty, entry=entry, price=price, reason="MONEY MODE TRAILING PROFIT")
                    state[symbol]["highest_since_entry"] = None
                    print(f"MONEY MODE TRAILING PROFIT SELL {qty:.6f} {symbol} | locked until tomorrow")
                except Exception as e:
                    print(f"SELL ERROR {symbol}: {e}")

                continue


def allowed_new_position_count():
    positions = get_all_positions()
    return max(0, MAX_POSITIONS - len(positions))


def calculate_new_position_notional():
    account = get_account()
    equity = float(account.equity)
    buying_power = float(account.buying_power)

    target_value = equity * TARGET_POSITION_VALUE_PCT
    max_value = equity * MAX_POSITION_VALUE_PCT

    usable_cash = max(0.0, buying_power - CASH_BUFFER)

    notional = min(target_value, max_value, usable_cash)

    return round(max(0.0, notional), 2)


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
        # Manual buy still respects strict lockout.
        liquid = []
        for s in scans:
            can_buy, reason = can_buy_symbol(s["symbol"])
            if not can_buy:
                continue
            if s["spread"] <= MAX_SPREAD:
                liquid.append(s)

        liquid.sort(key=lambda x: (-x["quality_score"], x["spread"]))
        picks = liquid

    if not picks:
        return "No money-mode candidates ready, or all candidates locked/held."

    bought = 0
    messages = []

    for candidate in picks:
        if bought >= MAX_NEW_BUYS_PER_LOOP:
            break

        symbol = candidate["symbol"]

        can_buy, reason = can_buy_symbol(symbol)
        if not can_buy:
            messages.append(f"SKIP {symbol} | {reason}")
            continue

        if not manual and not candidate["ready_to_buy"]:
            messages.append(f"SKIP {symbol} | not ready")
            continue

        try:
            notional = confidence_notional(candidate)

            if notional < MIN_ORDER_NOTIONAL:
                messages.append(f"SKIP {symbol} | not enough usable cash to buy. notional={notional:.2f}")
                continue

            confidence, confidence_label = calculate_confidence(candidate)
            reason = f"{'MANUAL' if manual else 'AUTO'} SNIPER {confidence_label} BUY"
            market_buy_notional(symbol, notional, reason=reason)
            state[symbol]["ref"] = candidate["price"]
            state[symbol]["highest_since_entry"] = candidate["price"]
            bought += 1
            messages.append(f"{reason} ${notional:.2f} of {symbol} | confidence={confidence:.2f}")
        except Exception as e:
            messages.append(f"BUY ERROR {symbol}: {e}")

    return " | ".join(messages) if messages else "No buy submitted."


def buy_custom_symbol(symbol: str):
    if not symbol or not symbol.replace(".", "").replace("-", "").isalnum():
        return {"ok": False, "message": "Invalid ticker"}

    if emergency_stop:
        return {"ok": False, "message": "BUY BLOCKED | emergency stop active"}

    if CUSTOM_BUY_REQUIRES_MARKET_OPEN:
        clock = trading_client.get_clock()
        if not clock.is_open:
            return {"ok": False, "message": "Market closed"}

    blocked, reason = risk_blocked()
    if blocked:
        return {"ok": False, "message": f"BUY BLOCKED | {reason}"}

    if allowed_new_position_count() <= 0:
        return {"ok": False, "message": f"BUY BLOCKED | max positions reached ({MAX_POSITIONS})"}

    can_buy, reason = can_buy_symbol(symbol)
    if not can_buy:
        return {"ok": False, "message": f"BUY BLOCKED | {reason}"}

    try:
        quote = get_quote(symbol)
    except Exception as e:
        return {"ok": False, "message": f"Could not get quote for {symbol}: {e}"}

    if quote["spread"] > MAX_SPREAD:
        return {
            "ok": False,
            "message": f"BUY BLOCKED | {symbol} spread too wide: {quote['spread']:.4f}",
        }

    notional = calculate_new_position_notional()

    if notional < MIN_ORDER_NOTIONAL:
        return {"ok": False, "message": f"Not enough usable cash to buy. notional={notional:.2f}"}

    add_symbol_to_universe(symbol, custom=True)

    try:
        market_buy_notional(symbol, notional, reason="CUSTOM MONEY MODE BUY")
        state[symbol]["ref"] = quote["mid"]
        state[symbol]["highest_since_entry"] = quote["mid"]

        # Immediately create/refresh a scan so the frontend can show it.
        scan = compute_scan(symbol)
        replaced = False
        for idx, existing in enumerate(latest_scans):
            if existing["symbol"] == symbol:
                latest_scans[idx] = scan
                replaced = True
                break

        if not replaced:
            latest_scans.append(scan)

        return {
            "ok": True,
            "message": f"CUSTOM BUY ${notional:.2f} of {symbol}. Added to managed universe.",
            "symbol": symbol,
            "notional": notional,
            "price": quote["mid"],
        }

    except Exception as e:
        return {"ok": False, "message": f"CUSTOM BUY ERROR {symbol}: {e}"}


# =========================
# STATUS
# =========================
def update_equity_curve(account):
    point = {
        "t": now_chart_time(),
        "value": float(account.equity),
    }

    if not equity_curve or equity_curve[-1]["value"] != point["value"]:
        equity_curve.append(point)

    if len(equity_curve) > 240:
        equity_curve.pop(0)


def build_status_payload(bot_name, scans):
    account = get_account()
    update_equity_curve(account)

    positions = get_all_positions()
    active_position = positions[0] if positions else None

    active_symbol = active_position["symbol"] if active_position else "—"
    active_qty = active_position["qty"] if active_position else 0.0
    active_entry = active_position["entry"] if active_position else 0.0
    active_price = active_position["price"] if active_position else 0.0
    active_pnl = active_position["pnl"] if active_position else 0.0
    active_pnl_pct = active_position["pnlPct"] if active_position else 0.0
    trailing_active = active_position["trailingActive"] if active_position else False
    trail_start_price = active_position["trailStartPrice"] if active_position else 0.0
    trail_floor = active_position["trailFloor"] if active_position else 0.0

    daily_pnl = get_daily_pnl()
    blocked, risk_reason = risk_blocked()
    notional = calculate_new_position_notional()
    market_status = get_market_status_payload()

    locked_symbols = sorted([s for s, d in locked_today.items() if d == today_str()])

    payload = {
        "id": "custom-buy-strict-lockout-live",
        "name": bot_name,
        "paperMode": PAPER,
        "botEnabled": bot_enabled,
        "manualOverride": manual_override,
        "emergencyStop": emergency_stop,
        "riskBlocked": blocked,
        "riskReason": risk_reason,
        "mode": "PROFIT_MODE_CUSTOM_BUY_STRICT_LOCKOUT",
        "market": market_status,
        "strictOneCyclePerStockPerDay": STRICT_ONE_CYCLE_PER_STOCK_PER_DAY,
        "allowCustomBuy": ALLOW_CUSTOM_BUY,
        "profitModeEnabled": PROFIT_MODE_ENABLED,
        "rotationModeEnabled": ROTATION_MODE_ENABLED,
        "rotationCooldownSeconds": ROTATION_COOLDOWN_SECONDS,
        "minBuyQualityScore": MIN_BUY_QUALITY_SCORE,
        "rotationMinQualityEdge": ROTATION_MIN_QUALITY_EDGE,
        "pdtAwareModeEnabled": PDT_AWARE_MODE_ENABLED,
        "pdtWarningEvents": pdt_warning_events[-50:],
        "todayBuyCount": today_buy_count(),
        "maxNewBuysPerDayPdtAware": MAX_NEW_BUYS_PER_DAY_PDT_AWARE,
        "alpacaRejectionEvents": alpaca_rejection_events[-50:],
        "pdtRejectionEvents": [e for e in alpaca_rejection_events[-50:] if e.get("type") == "PDT BLOCK"],
        "lockedSymbolsToday": locked_symbols,
        "customSymbols": sorted(list(custom_symbols.keys())),
        "maxPositions": MAX_POSITIONS,
        "newPositionNotional": notional,
        "allowedNewPositions": allowed_new_position_count(),
        "syncAllAlpacaPositions": SYNC_ALL_ALPACA_POSITIONS,
        "manageOutsideUniversePositions": MANAGE_OUTSIDE_UNIVERSE_POSITIONS,
        "universe": list(current_universe),
        "config": {
            "checkInterval": CHECK_INTERVAL,
            "universeRefreshSeconds": UNIVERSE_REFRESH_SECONDS,
            "minOrderNotional": MIN_ORDER_NOTIONAL,
            "cashBuffer": CASH_BUFFER,
            "maxSpread": MAX_SPREAD,
            "preferSpreadUnder": PREFER_SPREAD_UNDER,
            "dustThreshold": DUST_THRESHOLD,
            "maxPositions": MAX_POSITIONS,
            "targetPositionValuePct": TARGET_POSITION_VALUE_PCT,
            "maxPositionValuePct": MAX_POSITION_VALUE_PCT,
            "buyDip": BUY_DIP,
            "minPullback": MIN_PULLBACK,
            "maxPullback": MAX_PULLBACK,
            "stopLoss": STOP_LOSS,
            "trailStart": TRAIL_START,
            "trailGiveback": TRAIL_GIVEBACK,
            "maxDailyLoss": MAX_DAILY_LOSS,
            "maxTradesPerDay": MAX_TRADES_PER_DAY,
            "pdtAwareModeEnabled": PDT_AWARE_MODE_ENABLED,
            "avoidSameDayProfitSells": AVOID_SAME_DAY_PROFIT_SELLS,
            "avoidSameDayRotationSells": AVOID_SAME_DAY_ROTATION_SELLS,
            "minHoldMinutesBeforeProfitSell": MIN_HOLD_MINUTES_BEFORE_PROFIT_SELL,
            "minHoldMinutesBeforeRotation": MIN_HOLD_MINUTES_BEFORE_ROTATION,
            "hardStopLossPct": HARD_STOP_LOSS_PCT,
            "maxNewBuysPerDayPdtAware": MAX_NEW_BUYS_PER_DAY_PDT_AWARE,
        },
        "account": {
            "equity": float(account.equity),
            "buyingPower": float(account.buying_power),
            "cash": float(account.cash),
            "pnlDay": float(daily_pnl),
        },
        "activePosition": {
            "symbol": active_symbol,
            "qty": float(active_qty),
            "entry": float(active_entry),
            "price": float(active_price),
            "pnl": float(active_pnl),
            "pnlPct": float(active_pnl_pct),
            "trailingActive": bool(trailing_active),
            "trailStartPrice": float(trail_start_price),
            "trailFloor": float(trail_floor),
        },
        "positions": positions,
        "scans": [
            {
                "symbol": scan["symbol"],
                "price": float(scan["price"]),
                "ref": float(scan["ref"]),
                "trigger": float(scan["buy_trigger"]),
                "spread": float(scan["spread"]),
                "qty": float(scan["qty"]),
                "score": float(scan["score"]),
                "pullback": float(scan["pullback"]),
                "shortMomentum": float(scan["short_momentum"]),
                "qualityScore": float(scan["quality_score"]),
                "readyToBuy": bool(scan["ready_to_buy"]),
                "lockedToday": bool(scan["locked_today"]),
                "custom": bool(scan.get("custom", False)),
                "done": bool(scan["locked_today"]),
                "priceCurve": scan.get("price_curve", []),
                "confidence": float(scan.get("confidence", 0.0)),
                "confidenceLabel": scan.get("confidence_label", "LOW"),
                "sniperPass": bool(scan.get("sniper_pass", False)),
                "sniperReason": scan.get("sniper_reason", ""),
            }
            for scan in scans
        ],
        "logs": [
            f"MODE | PROFIT_MODE | max_positions={MAX_POSITIONS} | allowed_new={allowed_new_position_count()} | next_notional={notional:.2f}",
            f"PROFIT | enabled={PROFIT_MODE_ENABLED} | rotation={ROTATION_MODE_ENABLED} | min_quality={MIN_BUY_QUALITY_SCORE} | min_momentum={MIN_BUY_SHORT_MOMENTUM}",
            f"PDT AWARE | enabled={PDT_AWARE_MODE_ENABLED} | today_buys={today_buy_count()}/{MAX_NEW_BUYS_PER_DAY_PDT_AWARE} | warnings={len(pdt_warning_events)}",
            f"SNIPER | enabled={SNIPER_MODE_ENABLED} | confidence_sizing={CONFIDENCE_SIZING_ENABLED} | memory={STOCK_MEMORY_ENABLED} | timeline_events={len(trade_history)}",
            f"MARKET | {market_status.get('label', 'UNKNOWN')} | next_open={market_status.get('nextOpen', '')} | next_close={market_status.get('nextClose', '')}",
            f"CUSTOM | enabled={ALLOW_CUSTOM_BUY} | custom_symbols={', '.join(sorted(custom_symbols.keys())) if custom_symbols else 'none'}",
            f"LOCKOUT | strict={STRICT_ONE_CYCLE_PER_STOCK_PER_DAY} | locked_today={', '.join(locked_symbols) if locked_symbols else 'none'}",
            f"ALPACA REJECTIONS | events={len(alpaca_rejection_events)} | pdt={len([e for e in alpaca_rejection_events if e.get('type') == 'PDT BLOCK'])}",
            f"BOT | enabled={bot_enabled} | manual_override={manual_override} | emergency_stop={emergency_stop}",
            f"ACCOUNT | equity={float(account.equity):.2f} | buying_power={float(account.buying_power):.2f} | cash={float(account.cash):.2f}",
            f"DAILY PNL | {daily_pnl:.2f}",
            f"POSITIONS | {len(positions)}",
            f"ACTIVE | symbol={active_symbol} | qty={float(active_qty):.6f} | entry={float(active_entry):.2f}",
            f"TRADES | count={len(trade_events)}",
            f"RISK | blocked={blocked} | reason={risk_reason or 'none'}",
        ],
        "trades": trade_events[-50:],
        "equityCurve": equity_curve[-240:],
        "tradeTimeline": trade_timeline_payload(),
        "stockMemory": stock_memory_payload(),
        "sniperModeEnabled": SNIPER_MODE_ENABLED,
        "confidenceSizingEnabled": CONFIDENCE_SIZING_ENABLED,
        "stockMemoryEnabled": STOCK_MEMORY_ENABLED,
    }

    return payload


def update_status(bot_name, scans):
    payload = build_status_payload(bot_name, scans)

    latest_status.clear()
    latest_status.update(payload)


# =========================
# BOT LOOP
# =========================
def run_bot_loop():
    print("Custom Buy Strict Lockout Money Mode trading bot started...")

    refresh_universe_if_needed(force=True)
    reset_daily_flags_if_needed()
    update_status(BOT_NAME, [])

    while True:
        try:
            with bot_lock:
                reset_daily_flags_if_needed()
                refresh_universe_if_needed()

                clock = trading_client.get_clock()

                if not clock.is_open:
                    print("Market closed. Waiting...")
                    update_status(BOT_NAME, [])
                    time.sleep(CHECK_INTERVAL)
                    continue

                scans = []

                for symbol in current_universe:
                    try:
                        scan = compute_scan(symbol)
                        scans.append(scan)

                        print(
                            f"{symbol} | price={scan['price']:.2f} | ref={scan['ref']:.2f} "
                            f"| trigger={scan['buy_trigger']:.2f} | spread={scan['spread']:.4f} "
                            f"| pullback={scan['pullback']:.4f} | momentum={scan['short_momentum']:.4f} "
                            f"| quality={scan['quality_score']:.4f} | ready={scan['ready_to_buy']} "
                            f"| locked={scan['locked_today']} | custom={scan['custom']} | qty={scan['qty']:.6f}"
                        )

                    except Exception as e:
                        print(f"SCAN ERROR {symbol}: {e}")

                latest_scans.clear()
                latest_scans.extend(scans)

                if bot_enabled and not emergency_stop:
                    manage_money_mode_positions()

                    if PROFIT_MODE_ENABLED and ROTATION_MODE_ENABLED:
                        rotation_result = maybe_rotate_weakest_into_best(scans)
                        if rotation_result:
                            print(rotation_result)

                    if not manual_override:
                        result = money_mode_buy(scans, manual=False)
                        if result:
                            print(result)
                    else:
                        print("AUTO BUY PAUSED | manual override active")
                else:
                    print("BOT PAUSED OR EMERGENCY STOP ACTIVE")

                update_status(BOT_NAME, scans)

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(10)
