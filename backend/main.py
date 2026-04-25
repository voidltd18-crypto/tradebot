from fastapi import Request, HTTPException

DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY")

def verify_api_key(request: Request):
    key = request.headers.get("x-api-key")
    if key != DASHBOARD_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
import os
import time
import threading
from datetime import datetime, UTC
from typing import Dict, Any, List, Optional

import requests
from fastapi import FastAPI
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

# Money mode risk
MAX_POSITIONS = 12
MAX_NEW_BUYS_PER_LOOP = 1
MAX_POSITION_VALUE_PCT = 0.12
TARGET_POSITION_VALUE_PCT = 0.08
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
alpaca_rejection_events: List[Dict[str, Any]] = []
equity_curve: List[Dict[str, Any]] = []

bot_enabled = True
manual_override = False
emergency_stop = False

starting_equity_today: Optional[float] = None
starting_equity_day: Optional[str] = None

bot_thread_started = False
bot_lock = threading.Lock()


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
    }


@app.get("/status")
def get_status():
    return latest_status


@app.post("/pause")
def pause_bot():
    global bot_enabled
    bot_enabled = False
    notify("⏸️ Strict Lockout Money Mode paused")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot paused"}


@app.post("/resume")
def resume_bot():
    global bot_enabled, emergency_stop
    bot_enabled = True
    emergency_stop = False
    notify("▶️ Strict Lockout Money Mode resumed")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot resumed"}


@app.post("/manual-override/on")
def manual_override_on():
    global manual_override
    manual_override = True
    notify("🟠 Manual override ON. Auto-buy paused.")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Manual override ON. Auto-buy paused."}


@app.post("/manual-override/off")
def manual_override_off():
    global manual_override
    manual_override = False
    notify("🟢 Manual override OFF. Auto-buy active.")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Manual override OFF. Auto-buy active."}


@app.post("/manual-buy")
def manual_buy():
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
def custom_buy(symbol: str):
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
def manual_sell():
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
def sell_symbol(symbol: str):
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
def emergency_sell():
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

    bot_thread_started = True
    thread = threading.Thread(target=run_bot_loop, daemon=True)
    thread.start()


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
    notify(f"🟢 {reason}: ${round(notional_amount, 2)} {symbol}")

    if len(trade_events) > 200:
        trade_events.pop(0)


def market_sell_qty(symbol: str, qty: float, entry: float = 0.0, price: float = 0.0, reason="AUTO SELL"):
    rounded_qty = max(0, int(qty * 1_000_000) / 1_000_000)

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
        # IMPORTANT:
        # The bot DOES NOT block the sell itself.
        # It attempts the sell, and if Alpaca rejects it, we log/notify here.
        add_alpaca_rejection_event(symbol, reason, str(e))
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
    notify(f"🔴 {reason}: {symbol} | est PnL {round(estimated_pnl, 4)} ({round(estimated_pnl_pct, 2)}%)")

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

        if not scan["ready_to_buy"]:
            continue

        candidates.append(scan)

    candidates.sort(key=lambda x: (-x["quality_score"], x["spread"]))
    return candidates


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

    notional = calculate_new_position_notional()

    if notional < MIN_ORDER_NOTIONAL:
        return f"Not enough usable cash to buy. notional={notional:.2f}"

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
            reason = "MANUAL MONEY MODE BUY" if manual else "AUTO MONEY MODE BUY"
            market_buy_notional(symbol, notional, reason=reason)
            state[symbol]["ref"] = candidate["price"]
            state[symbol]["highest_since_entry"] = candidate["price"]
            bought += 1
            messages.append(f"{reason} ${notional:.2f} of {symbol}")
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
        "mode": "CUSTOM_BUY_STRICT_LOCKOUT_MONEY_MODE",
        "market": market_status,
        "strictOneCyclePerStockPerDay": STRICT_ONE_CYCLE_PER_STOCK_PER_DAY,
        "allowCustomBuy": ALLOW_CUSTOM_BUY,
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
            }
            for scan in scans
        ],
        "logs": [
            f"MODE | CUSTOM_BUY_STRICT_LOCKOUT_MONEY_MODE | max_positions={MAX_POSITIONS} | allowed_new={allowed_new_position_count()} | next_notional={notional:.2f}",
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
