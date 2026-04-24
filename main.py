import os
import time
import threading
from datetime import datetime, UTC
from typing import Dict, Any, List

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
ENABLE_MANUAL_BUTTONS = True

SAFE_UNIVERSE = [
    "PLUG",
    "OPEN",
    "LCID",
]

CHECK_INTERVAL = 60
UNIVERSE_REFRESH_SECONDS = 60 * 30

MIN_ORDER_NOTIONAL = 1.00
CASH_BUFFER = 0.50
MAX_SPREAD = 0.02

DUST_THRESHOLD = 0.1
TOP_PICKS = 3

BUY_DIP = 0.9995

STOP_LOSS = 0.985
TRAIL_START = 1.005
TRAIL_GIVEBACK = 0.995

BOT_NAME = "Cheap-stock rotating trailing-profit bot"


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

state = {
    symbol: {
        "ref": None,
        "highest_since_entry": None,
    }
    for symbol in current_universe
}

done_today: Dict[str, str] = {}
last_universe_refresh_ts = 0

latest_status: Dict[str, Any] = {}
latest_scans: List[Dict[str, Any]] = []

trade_events: List[Dict[str, Any]] = []
equity_curve: List[Dict[str, Any]] = []

bot_thread_started = False
bot_lock = threading.Lock()


# =========================
# FASTAPI
# =========================
app = FastAPI(title="Cheap Stock Trading Bot")

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
        "message": "Cheap-stock trading bot running",
        "status": "/status",
        "manual_buy": "/manual-buy",
        "manual_sell": "/manual-sell",
        "paperMode": PAPER,
    }


@app.get("/status")
def get_status():
    return latest_status


@app.post("/manual-buy")
def manual_buy():
    if not ENABLE_MANUAL_BUTTONS:
        return {"ok": False, "message": "Manual buttons disabled"}

    try:
        with bot_lock:
            clock = trading_client.get_clock()

            if not clock.is_open:
                return {"ok": False, "message": "Market closed"}

            if not latest_scans:
                return {"ok": False, "message": "No scan data yet"}

            buy_best_stock(latest_scans)
            update_status(BOT_NAME, latest_scans)

        return {"ok": True, "message": "Manual buy attempted"}

    except Exception as e:
        return {"ok": False, "message": str(e)}


@app.post("/manual-sell")
def manual_sell():
    if not ENABLE_MANUAL_BUTTONS:
        return {"ok": False, "message": "Manual buttons disabled"}

    try:
        with bot_lock:
            symbol, qty, entry = get_any_open_position()

            if not symbol or qty <= DUST_THRESHOLD:
                return {"ok": False, "message": "No open position to sell"}

            if has_open_order(symbol):
                return {"ok": False, "message": f"{symbol} already has open order"}

            market_sell_qty(symbol, qty)
            mark_done(symbol)

            if symbol in state:
                state[symbol]["highest_since_entry"] = None

            update_status(BOT_NAME, latest_scans)

        return {
            "ok": True,
            "message": f"Manual sell submitted for {symbol}",
            "symbol": symbol,
            "qty": qty,
            "entry": entry,
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
# DATE HELPERS
# =========================
def today_str():
    return datetime.now(UTC).strftime("%Y-%m-%d")


def now_time():
    return datetime.now(UTC).strftime("%H:%M:%S")


def now_chart_time():
    return datetime.now(UTC).strftime("%H:%M")


def reset_daily_flags_if_needed():
    today = today_str()
    stale_done = [symbol for symbol, day in done_today.items() if day != today]

    for symbol in stale_done:
        del done_today[symbol]


def mark_done(symbol: str):
    done_today[symbol] = today_str()


def is_done_today(symbol: str):
    return done_today.get(symbol) == today_str()


# =========================
# ACCOUNT / MARKET HELPERS
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


def get_any_open_position():
    for symbol in current_universe:
        qty, entry = get_position(symbol)

        if qty > DUST_THRESHOLD:
            return symbol, qty, entry

    return None, 0.0, 0.0


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


# =========================
# ORDER HELPERS
# =========================
def market_buy_notional(symbol: str, notional_amount: float):
    order = MarketOrderRequest(
        symbol=symbol,
        notional=round(notional_amount, 2),
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )

    trading_client.submit_order(order)

    trade_events.append(
        {
            "time": now_time(),
            "side": "BUY",
            "symbol": symbol,
            "amount": round(notional_amount, 2),
        }
    )

    if len(trade_events) > 100:
        trade_events.pop(0)


def market_sell_qty(symbol: str, qty: float):
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

    trade_events.append(
        {
            "time": now_time(),
            "side": "SELL",
            "symbol": symbol,
            "qty": rounded_qty,
        }
    )

    if len(trade_events) > 100:
        trade_events.pop(0)


def clean_dust_positions():
    for symbol in current_universe:
        qty, _ = get_position(symbol)
        rounded_qty = round(qty, 6)

        if 0 < qty < DUST_THRESHOLD and rounded_qty > 0 and not has_open_order(symbol):
            try:
                market_sell_qty(symbol, qty)
                print(f"CLEANED DUST {symbol} | qty={qty:.6f}")
            except Exception as e:
                print(f"DUST CLEAN ERROR {symbol}: {e}")


# =========================
# RULES
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

    held_symbol, held_qty, _ = get_any_open_position()

    if held_qty > DUST_THRESHOLD and held_symbol != symbol:
        print(f"SKIP {symbol} | another stock already open: {held_symbol}")
        return False

    return True


def can_sell(symbol: str):
    if is_done_today(symbol):
        print(f"SKIP {symbol} | already used today")
        return False

    if has_open_order(symbol):
        print(f"SKIP {symbol} | existing open order")
        return False

    return True


# =========================
# UNIVERSE / SCORING
# =========================
def refresh_universe_if_needed(force=False):
    global current_universe, state, last_universe_refresh_ts

    now = time.time()

    if not force and (now - last_universe_refresh_ts) < UNIVERSE_REFRESH_SECONDS:
        return

    new_universe = list(SAFE_UNIVERSE)
    new_state = {}

    for symbol in new_universe:
        old_state = state.get(symbol, {})
        new_state[symbol] = {
            "ref": old_state.get("ref"),
            "highest_since_entry": old_state.get("highest_since_entry"),
        }

    current_universe = new_universe
    state = new_state
    last_universe_refresh_ts = now

    print(f"CHEAP UNIVERSE REFRESHED: {', '.join(current_universe)}")


def compute_scan(symbol: str):
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

    score = (price / ref) - 1.0 if ref > 0 else 0.0
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
        "buy_trigger": buy_trigger,
        "highest_since_entry": state[symbol]["highest_since_entry"],
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

    candidates.sort(key=lambda x: (-x["score"], x["spread"]))
    return candidates[:TOP_PICKS]


# =========================
# STATUS PAYLOAD
# =========================
def update_equity_curve(account):
    point = {
        "t": now_chart_time(),
        "value": float(account.equity),
    }

    if not equity_curve or equity_curve[-1]["value"] != point["value"]:
        equity_curve.append(point)

    if len(equity_curve) > 120:
        equity_curve.pop(0)


def build_status_payload(bot_name, scans):
    account = trading_client.get_account()
    update_equity_curve(account)

    active_symbol, active_qty, active_entry = get_any_open_position()

    active_price = 0.0
    active_highest = 0.0
    trail_start_price = 0.0
    trail_floor = 0.0
    trailing_active = False

    if active_symbol:
        for scan in scans:
            if scan["symbol"] == active_symbol:
                active_price = float(scan["price"])
                active_highest = float(scan.get("highest_since_entry") or 0.0)
                break

        if active_entry > 0:
            trail_start_price = active_entry * TRAIL_START

            if active_highest > 0:
                trail_floor = active_highest * TRAIL_GIVEBACK

            trailing_active = active_price >= trail_start_price if active_price > 0 else False

    active_pnl_pct = 0.0

    if active_entry > 0 and active_price > 0:
        active_pnl_pct = ((active_price / active_entry) - 1.0) * 100.0

    payload = {
        "id": "cheap-live",
        "name": bot_name,
        "paperMode": PAPER,
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
        },
        "account": {
            "equity": float(account.equity),
            "buyingPower": float(account.buying_power),
            "cash": float(account.cash),
            "pnlDay": 0.0,
        },
        "activePosition": {
            "symbol": active_symbol or "—",
            "qty": float(active_qty),
            "entry": float(active_entry),
            "price": float(active_price),
            "pnlPct": float(active_pnl_pct),
            "trailingActive": bool(trailing_active),
            "trailStartPrice": float(trail_start_price),
            "trailFloor": float(trail_floor),
        },
        "scans": [
            {
                "symbol": scan["symbol"],
                "price": float(scan["price"]),
                "ref": float(scan["ref"]),
                "trigger": float(scan["buy_trigger"]),
                "spread": float(scan["spread"]),
                "qty": float(scan["qty"]),
                "score": float(scan["score"]),
                "done": bool(is_done_today(scan["symbol"])),
            }
            for scan in scans
        ],
        "logs": [
            f"ACCOUNT | buying_power={float(account.buying_power):.2f} | cash={float(account.cash):.2f}",
            f"ACTIVE | symbol={active_symbol or '—'} | qty={float(active_qty):.6f} | entry={float(active_entry):.2f}",
            f"TRADES | count={len(trade_events)}",
            f"EQUITY_CURVE | points={len(equity_curve)}",
        ],
        "trades": trade_events[-30:],
        "equityCurve": equity_curve[-120:],
    }

    return payload


def update_status(bot_name, scans):
    payload = build_status_payload(bot_name, scans)

    latest_status.clear()
    latest_status.update(payload)


# =========================
# TRADING LOGIC
# =========================
def manage_sells(scans):
    for scan in scans:
        symbol = scan["symbol"]
        qty = scan["qty"]
        entry = scan["entry"]
        price = scan["price"]
        highest = scan["highest_since_entry"]

        if is_done_today(symbol):
            continue

        if qty <= DUST_THRESHOLD:
            continue

        stop_price = entry * STOP_LOSS

        if price <= stop_price:
            if not can_sell(symbol):
                continue

            try:
                market_sell_qty(symbol, qty)
                mark_done(symbol)
                state[symbol]["highest_since_entry"] = None

                print(
                    f"STOP LOSS SELL {qty:.6f} {symbol} | "
                    f"entry={entry:.2f} stop={stop_price:.2f} price={price:.2f} | done for today"
                )
            except Exception as e:
                print(f"SELL ERROR {symbol}: {e}")

            continue

        trail_start_price = entry * TRAIL_START

        if price >= trail_start_price and highest is not None:
            trail_floor = highest * TRAIL_GIVEBACK

            print(
                f"{symbol} | trailing active | entry={entry:.2f} "
                f"| highest={highest:.2f} | trail_start={trail_start_price:.2f} "
                f"| trail_floor={trail_floor:.2f}"
            )

            if price <= trail_floor:
                if not can_sell(symbol):
                    continue

                try:
                    market_sell_qty(symbol, qty)
                    mark_done(symbol)
                    state[symbol]["highest_since_entry"] = None

                    print(
                        f"TRAILING PROFIT SELL {qty:.6f} {symbol} | "
                        f"entry={entry:.2f} highest={highest:.2f} "
                        f"trail_floor={trail_floor:.2f} price={price:.2f} | done for today"
                    )
                except Exception as e:
                    print(f"SELL ERROR {symbol}: {e}")

                continue


def buy_best_stock(scans):
    held_symbol, held_qty, _ = get_any_open_position()

    if held_qty > DUST_THRESHOLD:
        print(f"BUY BLOCKED | already holding {held_symbol}")
        return

    picks = pick_best_stocks(scans)

    if not picks:
        print("No eligible cheap stocks right now.")
        return

    usable_cash = max(0.0, get_buying_power() - CASH_BUFFER)

    if usable_cash < MIN_ORDER_NOTIONAL:
        print(f"Not enough usable cash to buy. usable_cash={usable_cash:.2f}")
        return

    for candidate in picks:
        symbol = candidate["symbol"]
        price = candidate["price"]
        ref = candidate["ref"]

        if not can_buy(symbol):
            continue

        if price > ref * BUY_DIP:
            print(f"SKIP {symbol} | not at buy trigger")
            continue

        notional = round(usable_cash, 2)

        if notional < MIN_ORDER_NOTIONAL:
            print(f"SKIP {symbol} | notional too small")
            return

        try:
            market_buy_notional(symbol, notional)
            state[symbol]["ref"] = price
            state[symbol]["highest_since_entry"] = price

            print(f"BUY ${notional:.2f} of {symbol}")
            return

        except Exception as e:
            print(f"BUY ERROR {symbol}: {e}")
            continue

    print("No ranked cheap stocks are at buy trigger right now.")


# =========================
# BOT LOOP
# =========================
def run_bot_loop():
    print("Cheap-stock rotating trailing-profit bot started...")

    refresh_universe_if_needed(force=True)
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

                account = trading_client.get_account()

                print(
                    f"ACCOUNT | buying_power={float(account.buying_power):.2f} "
                    f"| cash={float(account.cash):.2f}"
                )

                scans = []

                for symbol in current_universe:
                    try:
                        scan = compute_scan(symbol)
                        scans.append(scan)

                        print(
                            f"{symbol} | price={scan['price']:.2f} | ref={scan['ref']:.2f} "
                            f"| buy< {scan['buy_trigger']:.2f} | spread={scan['spread']:.4f} "
                            f"| qty={scan['qty']:.6f} | score={scan['score']:.4f}"
                        )

                    except Exception as e:
                        print(f"SCAN ERROR {symbol}: {e}")

                latest_scans.clear()
                latest_scans.extend(scans)

                manage_sells(scans)
                buy_best_stock(scans)

                update_status(BOT_NAME, scans)

                remaining = [symbol for symbol in current_universe if not is_done_today(symbol)]

                if not remaining:
                    print("ALL CHEAP STOCKS USED TODAY | waiting for next day reset")

            time.sleep(CHECK_INTERVAL)

        except Exception as e:
            print(f"Main loop error: {e}")
            time.sleep(10)
