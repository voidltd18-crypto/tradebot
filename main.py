
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


# =========================
# CONFIG
# =========================
API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")

PAPER = os.getenv("PAPER", "false").lower() == "true"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BOT_NAME = "Synced portfolio trailing-profit bot"

SAFE_UNIVERSE = [
    "PLUG",
    "OPEN",
    "LCID",
    "F",
    "SOFI",
    "RIVN",
    "AAL",
    "NIO",
]

CHECK_INTERVAL = 60
UNIVERSE_REFRESH_SECONDS = 60 * 30

MIN_ORDER_NOTIONAL = 1.00
CASH_BUFFER = 0.50
MAX_SPREAD = 0.02

DUST_THRESHOLD = 0.1
TOP_PICKS = 5

BUY_DIP = 0.9995

STOP_LOSS = 0.985
TRAIL_START = 1.005
TRAIL_GIVEBACK = 0.995

MAX_DAILY_LOSS = -10.00
MAX_TRADES_PER_DAY = 10

ENABLE_MANUAL_BUTTONS = True

# This is the key upgrade:
# True = bot manages every Alpaca position it can see, not just one symbol.
SYNC_ALL_ALPACA_POSITIONS = True

# True = bot can auto-sell positions even if they are outside SAFE_UNIVERSE.
# Safer default is False.
MANAGE_OUTSIDE_UNIVERSE_POSITIONS = False


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

state: Dict[str, Dict[str, Any]] = {
    symbol: {
        "ref": None,
        "highest_since_entry": None,
        "price_curve": [],
    }
    for symbol in current_universe
}

done_today: Dict[str, str] = {}
last_universe_refresh_ts = 0

latest_status: Dict[str, Any] = {}
latest_scans: List[Dict[str, Any]] = []

trade_events: List[Dict[str, Any]] = []
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
app = FastAPI(title="Synced Trading Bot Backend")

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
        "message": "Synced trading bot backend running",
        "status": "/status",
        "manual_buy": "/manual-buy",
        "manual_sell": "/manual-sell",
        "sell_symbol": "/sell/{symbol}",
        "emergency_sell": "/emergency-sell",
        "pause": "/pause",
        "resume": "/resume",
        "manual_override_on": "/manual-override/on",
        "manual_override_off": "/manual-override/off",
        "paperMode": PAPER,
        "syncAllAlpacaPositions": SYNC_ALL_ALPACA_POSITIONS,
    }


@app.get("/status")
def get_status():
    return latest_status


@app.post("/pause")
def pause_bot():
    global bot_enabled
    bot_enabled = False
    notify("⏸️ Bot paused")
    update_status(BOT_NAME, latest_scans)
    return {"ok": True, "message": "Bot paused"}


@app.post("/resume")
def resume_bot():
    global bot_enabled, emergency_stop
    bot_enabled = True
    emergency_stop = False
    notify("▶️ Bot resumed")
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

            result = buy_best_stock(latest_scans, manual=True)
            update_status(BOT_NAME, latest_scans)

            return {"ok": True, "message": result or "Manual buy attempted"}

    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/manual-sell")
def manual_sell():
    if not ENABLE_MANUAL_BUTTONS:
        return {"ok": False, "message": "Manual buttons disabled"}

    try:
        with bot_lock:
            result = close_largest_position(reason="MANUAL SELL")
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
            notify("🚨 Emergency stop activated")
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
# HELPERS
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


def ensure_symbol_state(symbol: str):
    if symbol not in state:
        state[symbol] = {
            "ref": None,
            "highest_since_entry": None,
            "price_curve": [],
        }


def reset_daily_flags_if_needed():
    global starting_equity_today, starting_equity_day

    today = today_str()

    stale_done = [symbol for symbol, day in done_today.items() if day != today]
    for symbol in stale_done:
        del done_today[symbol]

    if starting_equity_day != today:
        try:
            account = trading_client.get_account()
            starting_equity_today = float(account.equity)
            starting_equity_day = today
            trade_events.clear()
            equity_curve.clear()
        except Exception:
            pass


def mark_done(symbol: str):
    done_today[symbol] = today_str()


def is_done_today(symbol: str):
    return done_today.get(symbol) == today_str()


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

            ensure_symbol_state(symbol)

            highest = state[symbol].get("highest_since_entry")
            if highest is None or quote_price > highest:
                state[symbol]["highest_since_entry"] = quote_price

            trail_start_price = entry * TRAIL_START if entry > 0 else 0.0
            trail_floor = (state[symbol]["highest_since_entry"] or 0.0) * TRAIL_GIVEBACK
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
                    "highest": state[symbol]["highest_since_entry"] or 0.0,
                    "trailStartPrice": trail_start_price,
                    "trailFloor": trail_floor,
                    "trailingActive": trailing_active,
                    "inUniverse": symbol in current_universe,
                }
            )

        except Exception:
            continue

    positions.sort(key=lambda p: abs(p.get("marketValue", 0.0)), reverse=True)
    return positions


def get_largest_position():
    positions = get_all_positions()
    if not positions:
        return None
    return positions[0]


def get_any_open_position():
    position = get_largest_position()

    if not position:
        return None, 0.0, 0.0

    return position["symbol"], position["qty"], position["entry"]


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


def get_buying_power():
    account = trading_client.get_account()
    return float(account.buying_power)


def get_daily_pnl():
    global starting_equity_today

    try:
        account = trading_client.get_account()
        equity = float(account.equity)

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
    rounded_qty = round(qty, 6)

    if rounded_qty <= 0:
        return

    order = MarketOrderRequest(
        symbol=symbol,
        qty=rounded_qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )

    trading_client.submit_order(order)

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
    mark_done(symbol)

    if symbol in state:
        state[symbol]["highest_since_entry"] = None

    return {
        "ok": True,
        "message": f"{reason} submitted for {symbol}",
        "symbol": symbol,
        "qty": qty,
        "entry": entry,
        "price": price,
    }


def close_largest_position(reason="MANUAL SELL"):
    position = get_largest_position()

    if not position:
        return {"ok": False, "message": "No open position to sell"}

    return close_position(position, reason=reason)


def close_position_by_symbol(symbol: str, reason="MANUAL SYMBOL SELL"):
    positions = get_all_positions()

    for position in positions:
        if position["symbol"] == symbol:
            return close_position(position, reason=reason)

    return {"ok": False, "message": f"No open position found for {symbol}"}


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
        "message": f"{reason} attempted for {len(positions)} positions",
        "results": results,
    }


def clean_dust_positions():
    for position in get_all_positions():
        symbol = position["symbol"]
        qty = position["qty"]
        entry = position["entry"]
        price = position["price"]
        rounded_qty = round(qty, 6)

        if 0 < qty < DUST_THRESHOLD and rounded_qty > 0 and not has_open_order(symbol):
            try:
                market_sell_qty(symbol, qty, entry=entry, price=price, reason="DUST CLEAN")
                print(f"CLEANED DUST {symbol} | qty={qty:.6f}")
            except Exception as e:
                print(f"DUST CLEAN ERROR {symbol}: {e}")


# =========================
# RULES + SCORING
# =========================
def can_buy(symbol: str):
    if is_done_today(symbol):
        print(f"SKIP {symbol} | already used today")
        return False

    if has_open_order(symbol):
        print(f"SKIP {symbol} | existing open order")
        return False

    qty, _ = get_position(symbol)

    if qty > DUST_THRESHOLD:
        print(f"SKIP {symbol} | already holding position")
        return False

    # Even in synced mode, keep one new auto-entry at a time unless existing holdings came from previous sessions.
    return True


def can_sell_position(position: Dict[str, Any]):
    symbol = position["symbol"]

    if not MANAGE_OUTSIDE_UNIVERSE_POSITIONS and symbol not in current_universe:
        return False, f"{symbol} outside universe"

    if is_done_today(symbol):
        return False, f"{symbol} already done today"

    if has_open_order(symbol):
        return False, f"{symbol} existing open order"

    return True, ""


def refresh_universe_if_needed(force=False):
    global current_universe, state, last_universe_refresh_ts

    now = time.time()

    if not force and (now - last_universe_refresh_ts) < UNIVERSE_REFRESH_SECONDS:
        return

    new_universe = list(SAFE_UNIVERSE)

    for symbol in new_universe:
        ensure_symbol_state(symbol)

    current_universe = new_universe
    last_universe_refresh_ts = now

    print(f"UNIVERSE REFRESHED: {', '.join(current_universe)}")


def compute_scan(symbol: str):
    ensure_symbol_state(symbol)

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
        highest = state[symbol]["highest_since_entry"]

        if highest is None or price > highest:
            state[symbol]["highest_since_entry"] = price
    else:
        state[symbol]["highest_since_entry"] = None

    state[symbol]["price_curve"].append({"t": now_chart_time(), "value": price})
    if len(state[symbol]["price_curve"]) > 120:
        state[symbol]["price_curve"].pop(0)

    score = (price / ref) - 1.0 if ref > 0 else 0.0
    dip_strength = max(0.0, (ref - price) / ref) if ref > 0 else 0.0
    tightness_score = max(0.0, MAX_SPREAD - spread)
    momentum_rank = (dip_strength * 2.0) + tightness_score

    buy_trigger = ref * BUY_DIP

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
        "momentum_rank": momentum_rank,
        "buy_trigger": buy_trigger,
        "highest_since_entry": state[symbol]["highest_since_entry"],
        "price_curve": state[symbol]["price_curve"],
    }


def pick_best_stocks(scans):
    candidates = []

    for scan in scans:
        symbol = scan["symbol"]

        if is_done_today(symbol):
            print(f"SKIP {symbol} | already used today")
            continue

        if scan["spread"] > MAX_SPREAD:
            print(f"SKIP {symbol} | spread too wide: {scan['spread']:.4f}")
            continue

        candidates.append(scan)

    candidates.sort(key=lambda x: (-x["momentum_rank"], x["spread"]))
    return candidates[:TOP_PICKS]


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
    account = trading_client.get_account()
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

    payload = {
        "id": "synced-live",
        "name": bot_name,
        "paperMode": PAPER,
        "botEnabled": bot_enabled,
        "manualOverride": manual_override,
        "emergencyStop": emergency_stop,
        "riskBlocked": blocked,
        "riskReason": risk_reason,
        "syncAllAlpacaPositions": SYNC_ALL_ALPACA_POSITIONS,
        "manageOutsideUniversePositions": MANAGE_OUTSIDE_UNIVERSE_POSITIONS,
        "universe": list(current_universe),
        "config": {
            "checkInterval": CHECK_INTERVAL,
            "universeRefreshSeconds": UNIVERSE_REFRESH_SECONDS,
            "minOrderNotional": MIN_ORDER_NOTIONAL,
            "cashBuffer": CASH_BUFFER,
            "maxSpread": MAX_SPREAD,
            "dustThreshold": DUST_THRESHOLD,
            "topPicks": TOP_PICKS,
            "buyDip": BUY_DIP,
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
                "momentumRank": float(scan["momentum_rank"]),
                "done": bool(is_done_today(scan["symbol"])),
                "priceCurve": scan.get("price_curve", []),
            }
            for scan in scans
        ],
        "logs": [
            f"BOT | enabled={bot_enabled} | manual_override={manual_override} | emergency_stop={emergency_stop}",
            f"SYNC | all_positions={SYNC_ALL_ALPACA_POSITIONS} | positions={len(positions)}",
            f"ACCOUNT | equity={float(account.equity):.2f} | buying_power={float(account.buying_power):.2f} | cash={float(account.cash):.2f}",
            f"DAILY PNL | {daily_pnl:.2f}",
            f"ACTIVE | symbol={active_symbol} | qty={float(active_qty):.6f} | entry={float(active_entry):.2f}",
            f"TRADES | count={len(trade_events)}",
            f"EQUITY_CURVE | points={len(equity_curve)}",
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
# LOGIC
# =========================
def manage_synced_positions():
    positions = get_all_positions()

    for position in positions:
        symbol = position["symbol"]
        qty = position["qty"]
        entry = position["entry"]
        price = position["price"]
        highest = position["highest"]

        allowed, reason = can_sell_position(position)
        if not allowed:
            print(f"SKIP SELL {symbol} | {reason}")
            continue

        stop_price = entry * STOP_LOSS

        if price > 0 and price <= stop_price:
            try:
                market_sell_qty(symbol, qty, entry=entry, price=price, reason="SYNCED STOP LOSS")
                mark_done(symbol)
                state[symbol]["highest_since_entry"] = None
                print(f"SYNCED STOP LOSS SELL {qty:.6f} {symbol}")
            except Exception as e:
                print(f"SELL ERROR {symbol}: {e}")

            continue

        trail_start_price = entry * TRAIL_START

        if price >= trail_start_price and highest is not None:
            trail_floor = highest * TRAIL_GIVEBACK

            if price <= trail_floor:
                try:
                    market_sell_qty(symbol, qty, entry=entry, price=price, reason="SYNCED TRAILING PROFIT")
                    mark_done(symbol)
                    state[symbol]["highest_since_entry"] = None
                    print(f"SYNCED TRAILING PROFIT SELL {qty:.6f} {symbol}")
                except Exception as e:
                    print(f"SELL ERROR {symbol}: {e}")

                continue


def buy_best_stock(scans, manual=False):
    if emergency_stop:
        return "BUY BLOCKED | emergency stop active"

    blocked, reason = risk_blocked()
    if blocked:
        return f"BUY BLOCKED | {reason}"

    positions = get_all_positions()
    if positions:
        return f"BUY BLOCKED | already holding {len(positions)} position(s)"

    picks = pick_best_stocks(scans)

    if not picks:
        return "No eligible stocks right now."

    usable_cash = max(0.0, get_buying_power() - CASH_BUFFER)

    if usable_cash < MIN_ORDER_NOTIONAL:
        return f"Not enough usable cash to buy. usable_cash={usable_cash:.2f}"

    for candidate in picks:
        symbol = candidate["symbol"]
        price = candidate["price"]
        ref = candidate["ref"]

        if not can_buy(symbol):
            continue

        if not manual and price > ref * BUY_DIP:
            continue

        notional = round(usable_cash, 2)

        if notional < MIN_ORDER_NOTIONAL:
            return f"SKIP {symbol} | notional too small"

        try:
            reason = "MANUAL BUY" if manual else "AUTO BUY"
            market_buy_notional(symbol, notional, reason=reason)
            state[symbol]["ref"] = price
            state[symbol]["highest_since_entry"] = price

            message = f"{reason} ${notional:.2f} of {symbol}"
            print(message)
            return message

        except Exception as e:
            print(f"BUY ERROR {symbol}: {e}")
            continue

    return "No ranked stocks are at buy trigger right now."


# =========================
# BOT LOOP
# =========================
def run_bot_loop():
    print("Synced trading bot started...")

    refresh_universe_if_needed(force=True)
    reset_daily_flags_if_needed()
    update_status(BOT_NAME, [])

    while True:
        try:
            with bot_lock:
                reset_daily_flags_if_needed()
                refresh_universe_if_needed()

                clean_dust_positions()

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
                            f"| buy< {scan['buy_trigger']:.2f} | spread={scan['spread']:.4f} "
                            f"| qty={scan['qty']:.6f} | rank={scan['momentum_rank']:.4f}"
                        )

                    except Exception as e:
                        print(f"SCAN ERROR {symbol}: {e}")

                latest_scans.clear()
                latest_scans.extend(scans)

                if bot_enabled and not emergency_stop:
                    manage_synced_positions()

                    if not manual_override:
                        result = buy_best_stock(scans, manual=False)
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
