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

API_KEY = os.getenv("APCA_API_KEY_ID")
API_SECRET = os.getenv("APCA_API_SECRET_KEY")
PAPER = os.getenv("PAPER", "false").lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BOT_NAME = "Pro multi-stock rotating trailing-profit bot"
SAFE_UNIVERSE = ["PLUG", "OPEN", "LCID", "F", "SOFI", "RIVN", "AAL", "NIO"]

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

if not API_KEY or not API_SECRET:
    raise RuntimeError("Missing APCA_API_KEY_ID or APCA_API_SECRET_KEY")

trading_client = TradingClient(API_KEY, API_SECRET, paper=PAPER)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)

current_universe = list(SAFE_UNIVERSE)
state = {s: {"ref": None, "highest_since_entry": None, "price_curve": []} for s in current_universe}
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

app = FastAPI(title="Pro Trading Bot Backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
def root():
    return {"message":"Pro trading bot backend running","status":"/status","paperMode":PAPER}

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
            if not trading_client.get_clock().is_open:
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
            result = close_current_position(reason="MANUAL SELL")
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
            result = close_current_position(reason="EMERGENCY SELL")
            notify("🚨 Emergency stop activated")
            update_status(BOT_NAME, latest_scans)
            return {**result, "emergencyStop": True, "botEnabled": False}
    except Exception as e:
        return {"ok": False, "message": str(e)}

@app.on_event("startup")
def startup_event():
    global bot_thread_started
    if bot_thread_started:
        return
    bot_thread_started = True
    threading.Thread(target=run_bot_loop, daemon=True).start()

def today_str(): return datetime.now(UTC).strftime("%Y-%m-%d")
def now_time(): return datetime.now(UTC).strftime("%H:%M:%S")
def now_chart_time(): return datetime.now(UTC).strftime("%H:%M")

def notify(message: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except Exception:
        pass

def reset_daily_flags_if_needed():
    global starting_equity_today, starting_equity_day
    today = today_str()
    for symbol, day in list(done_today.items()):
        if day != today:
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

def mark_done(symbol: str): done_today[symbol] = today_str()
def is_done_today(symbol: str): return done_today.get(symbol) == today_str()

def get_quote(symbol: str):
    quote = data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))[symbol]
    bid, ask = quote.bid_price, quote.ask_price
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        raise ValueError(f"Bad quote for {symbol}")
    mid = (bid + ask) / 2.0
    return {"bid": float(bid), "ask": float(ask), "mid": float(mid), "spread": float((ask - bid) / mid)}

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
        orders = trading_client.get_orders(filter=GetOrdersRequest(status=QueryOrderStatus.OPEN))
        return orders if symbol is None else [o for o in orders if o.symbol == symbol]
    except Exception:
        return []

def has_open_order(symbol: str): return len(get_open_orders(symbol)) > 0
def get_buying_power(): return float(trading_client.get_account().buying_power)

def get_daily_pnl():
    global starting_equity_today
    try:
        equity = float(trading_client.get_account().equity)
        if starting_equity_today is None:
            starting_equity_today = equity
        return equity - starting_equity_today
    except Exception:
        return 0.0

def daily_trade_count(): return len([t for t in trade_events if t.get("day") == today_str()])

def risk_blocked():
    pnl = get_daily_pnl()
    if pnl <= MAX_DAILY_LOSS: return True, f"Max daily loss hit: {pnl:.2f}"
    if daily_trade_count() >= MAX_TRADES_PER_DAY: return True, "Max trades per day reached"
    return False, ""

def market_buy_notional(symbol: str, notional_amount: float, reason="AUTO BUY"):
    trading_client.submit_order(MarketOrderRequest(symbol=symbol, notional=round(notional_amount, 2), side=OrderSide.BUY, time_in_force=TimeInForce.DAY))
    trade_events.append({"day": today_str(), "time": now_time(), "side": "BUY", "symbol": symbol, "amount": round(notional_amount, 2), "reason": reason, "pnl": 0.0})
    notify(f"🟢 {reason}: ${round(notional_amount, 2)} {symbol}")
    if len(trade_events) > 200: trade_events.pop(0)

def market_sell_qty(symbol: str, qty: float, entry: float = 0.0, price: float = 0.0, reason="AUTO SELL"):
    rounded_qty = round(qty, 6)
    if rounded_qty <= 0: return
    trading_client.submit_order(MarketOrderRequest(symbol=symbol, qty=rounded_qty, side=OrderSide.SELL, time_in_force=TimeInForce.DAY))
    pnl = (price - entry) * rounded_qty if entry > 0 and price > 0 else 0.0
    pnl_pct = ((price / entry) - 1.0) * 100.0 if entry > 0 and price > 0 else 0.0
    trade_events.append({"day": today_str(), "time": now_time(), "side": "SELL", "symbol": symbol, "qty": rounded_qty, "reason": reason, "pnl": round(pnl, 4), "pnlPct": round(pnl_pct, 4)})
    notify(f"🔴 {reason}: {symbol} | est PnL {round(pnl, 4)} ({round(pnl_pct, 2)}%)")
    if len(trade_events) > 200: trade_events.pop(0)

def close_current_position(reason="MANUAL SELL"):
    symbol, qty, entry = get_any_open_position()
    if not symbol or qty <= DUST_THRESHOLD:
        return {"ok": False, "message": "No open position to sell"}
    if has_open_order(symbol):
        return {"ok": False, "message": f"{symbol} already has open order"}
    price = get_quote(symbol)["mid"]
    market_sell_qty(symbol, qty, entry=entry, price=price, reason=reason)
    mark_done(symbol)
    if symbol in state: state[symbol]["highest_since_entry"] = None
    return {"ok": True, "message": f"{reason} submitted for {symbol}", "symbol": symbol, "qty": qty, "entry": entry, "price": price}

def clean_dust_positions():
    for symbol in current_universe:
        qty, entry = get_position(symbol)
        if 0 < qty < DUST_THRESHOLD and round(qty, 6) > 0 and not has_open_order(symbol):
            try:
                market_sell_qty(symbol, qty, entry=entry, price=get_quote(symbol)["mid"], reason="DUST CLEAN")
            except Exception as e:
                print(f"DUST CLEAN ERROR {symbol}: {e}")

def can_buy(symbol: str):
    if is_done_today(symbol) or has_open_order(symbol): return False
    qty, _ = get_position(symbol)
    if qty > DUST_THRESHOLD: return False
    held_symbol, held_qty, _ = get_any_open_position()
    if held_qty > DUST_THRESHOLD and held_symbol != symbol: return False
    return True

def can_sell(symbol: str): return not is_done_today(symbol) and not has_open_order(symbol)

def refresh_universe_if_needed(force=False):
    global current_universe, state, last_universe_refresh_ts
    now = time.time()
    if not force and (now - last_universe_refresh_ts) < UNIVERSE_REFRESH_SECONDS: return
    new_state = {}
    for symbol in SAFE_UNIVERSE:
        old = state.get(symbol, {})
        new_state[symbol] = {"ref": old.get("ref"), "highest_since_entry": old.get("highest_since_entry"), "price_curve": old.get("price_curve", [])}
    current_universe = list(SAFE_UNIVERSE)
    state = new_state
    last_universe_refresh_ts = now

def compute_scan(symbol: str):
    quote = get_quote(symbol)
    qty, entry = get_position(symbol)
    price, spread = quote["mid"], quote["spread"]
    if state[symbol]["ref"] is None: state[symbol]["ref"] = price
    ref = state[symbol]["ref"]
    if price > ref:
        state[symbol]["ref"] = price
        ref = price
    if qty > DUST_THRESHOLD:
        highest = state[symbol]["highest_since_entry"]
        if highest is None or price > highest: state[symbol]["highest_since_entry"] = price
    else:
        state[symbol]["highest_since_entry"] = None
    state[symbol]["price_curve"].append({"t": now_chart_time(), "value": price})
    if len(state[symbol]["price_curve"]) > 120: state[symbol]["price_curve"].pop(0)
    score = (price / ref) - 1.0 if ref > 0 else 0.0
    dip_strength = max(0.0, (ref - price) / ref) if ref > 0 else 0.0
    tightness_score = max(0.0, MAX_SPREAD - spread)
    momentum_rank = (dip_strength * 2.0) + tightness_score
    return {"symbol": symbol, "price": price, "spread": spread, "bid": quote["bid"], "ask": quote["ask"], "qty": qty, "entry": entry, "ref": ref, "score": score, "momentum_rank": momentum_rank, "buy_trigger": ref * BUY_DIP, "highest_since_entry": state[symbol]["highest_since_entry"], "price_curve": state[symbol]["price_curve"]}

def pick_best_stocks(scans):
    candidates = [s for s in scans if not is_done_today(s["symbol"]) and s["spread"] <= MAX_SPREAD]
    candidates.sort(key=lambda x: (-x["momentum_rank"], x["spread"]))
    return candidates[:TOP_PICKS]

def update_equity_curve(account):
    point = {"t": now_chart_time(), "value": float(account.equity)}
    if not equity_curve or equity_curve[-1]["value"] != point["value"]: equity_curve.append(point)
    if len(equity_curve) > 240: equity_curve.pop(0)

def build_status_payload(bot_name, scans):
    account = trading_client.get_account()
    update_equity_curve(account)
    active_symbol, active_qty, active_entry = get_any_open_position()
    active_price, active_highest, trail_start_price, trail_floor, trailing_active = 0.0, 0.0, 0.0, 0.0, False
    if active_symbol:
        match = next((s for s in scans if s["symbol"] == active_symbol), None)
        if match:
            active_price = float(match["price"])
            active_highest = float(match.get("highest_since_entry") or 0.0)
        else:
            active_price = get_quote(active_symbol)["mid"]
        if active_entry > 0:
            trail_start_price = active_entry * TRAIL_START
            trail_floor = active_highest * TRAIL_GIVEBACK if active_highest > 0 else 0.0
            trailing_active = active_price >= trail_start_price if active_price > 0 else False
    active_pnl_pct = ((active_price / active_entry) - 1.0) * 100.0 if active_entry > 0 and active_price > 0 else 0.0
    active_pnl = (active_price - active_entry) * active_qty if active_entry > 0 and active_price > 0 else 0.0
    daily_pnl = get_daily_pnl()
    blocked, risk_reason = risk_blocked()
    return {
        "id": "pro-live", "name": bot_name, "paperMode": PAPER, "botEnabled": bot_enabled, "manualOverride": manual_override, "emergencyStop": emergency_stop, "riskBlocked": blocked, "riskReason": risk_reason,
        "universe": list(current_universe),
        "config": {"checkInterval": CHECK_INTERVAL, "universeRefreshSeconds": UNIVERSE_REFRESH_SECONDS, "minOrderNotional": MIN_ORDER_NOTIONAL, "cashBuffer": CASH_BUFFER, "maxSpread": MAX_SPREAD, "dustThreshold": DUST_THRESHOLD, "topPicks": TOP_PICKS, "buyDip": BUY_DIP, "stopLoss": STOP_LOSS, "trailStart": TRAIL_START, "trailGiveback": TRAIL_GIVEBACK, "maxDailyLoss": MAX_DAILY_LOSS, "maxTradesPerDay": MAX_TRADES_PER_DAY},
        "account": {"equity": float(account.equity), "buyingPower": float(account.buying_power), "cash": float(account.cash), "pnlDay": float(daily_pnl)},
        "activePosition": {"symbol": active_symbol or "—", "qty": float(active_qty), "entry": float(active_entry), "price": float(active_price), "pnl": float(active_pnl), "pnlPct": float(active_pnl_pct), "trailingActive": bool(trailing_active), "trailStartPrice": float(trail_start_price), "trailFloor": float(trail_floor)},
        "scans": [{"symbol": s["symbol"], "price": float(s["price"]), "ref": float(s["ref"]), "trigger": float(s["buy_trigger"]), "spread": float(s["spread"]), "qty": float(s["qty"]), "score": float(s["score"]), "momentumRank": float(s["momentum_rank"]), "done": bool(is_done_today(s["symbol"])), "priceCurve": s.get("price_curve", [])} for s in scans],
        "logs": [f"BOT | enabled={bot_enabled} | manual_override={manual_override} | emergency_stop={emergency_stop}", f"ACCOUNT | equity={float(account.equity):.2f} | buying_power={float(account.buying_power):.2f} | cash={float(account.cash):.2f}", f"DAILY PNL | {daily_pnl:.2f}", f"ACTIVE | symbol={active_symbol or '—'} | qty={float(active_qty):.6f} | entry={float(active_entry):.2f}", f"TRADES | count={len(trade_events)}", f"EQUITY_CURVE | points={len(equity_curve)}", f"RISK | blocked={blocked} | reason={risk_reason or 'none'}"],
        "trades": trade_events[-50:], "equityCurve": equity_curve[-240:]
    }

def update_status(bot_name, scans):
    latest_status.clear()
    latest_status.update(build_status_payload(bot_name, scans))

def manage_sells(scans):
    for scan in scans:
        symbol, qty, entry, price, highest = scan["symbol"], scan["qty"], scan["entry"], scan["price"], scan["highest_since_entry"]
        if is_done_today(symbol) or qty <= DUST_THRESHOLD: continue
        if price <= entry * STOP_LOSS and can_sell(symbol):
            market_sell_qty(symbol, qty, entry=entry, price=price, reason="STOP LOSS"); mark_done(symbol); state[symbol]["highest_since_entry"] = None; continue
        if price >= entry * TRAIL_START and highest is not None:
            if price <= highest * TRAIL_GIVEBACK and can_sell(symbol):
                market_sell_qty(symbol, qty, entry=entry, price=price, reason="TRAILING PROFIT"); mark_done(symbol); state[symbol]["highest_since_entry"] = None; continue

def buy_best_stock(scans, manual=False):
    if emergency_stop: return "BUY BLOCKED | emergency stop active"
    blocked, reason = risk_blocked()
    if blocked: return f"BUY BLOCKED | {reason}"
    held_symbol, held_qty, _ = get_any_open_position()
    if held_qty > DUST_THRESHOLD: return f"BUY BLOCKED | already holding {held_symbol}"
    picks = pick_best_stocks(scans)
    if not picks: return "No eligible stocks right now."
    usable_cash = max(0.0, get_buying_power() - CASH_BUFFER)
    if usable_cash < MIN_ORDER_NOTIONAL: return f"Not enough usable cash to buy. usable_cash={usable_cash:.2f}"
    for c in picks:
        if not can_buy(c["symbol"]): continue
        if not manual and c["price"] > c["ref"] * BUY_DIP: continue
        notional = round(usable_cash, 2)
        reason = "MANUAL BUY" if manual else "AUTO BUY"
        market_buy_notional(c["symbol"], notional, reason=reason)
        state[c["symbol"]]["ref"] = c["price"]
        state[c["symbol"]]["highest_since_entry"] = c["price"]
        return f"{reason} ${notional:.2f} of {c['symbol']}"
    return "No ranked stocks are at buy trigger right now."

def run_bot_loop():
    print("Pro trading bot started...")
    refresh_universe_if_needed(force=True)
    reset_daily_flags_if_needed()
    update_status(BOT_NAME, [])
    while True:
        try:
            with bot_lock:
                reset_daily_flags_if_needed(); refresh_universe_if_needed(); clean_dust_positions()
                if not trading_client.get_clock().is_open:
                    update_status(BOT_NAME, []); time.sleep(CHECK_INTERVAL); continue
                scans = []
                for symbol in current_universe:
                    try: scans.append(compute_scan(symbol))
                    except Exception as e: print(f"SCAN ERROR {symbol}: {e}")
                latest_scans.clear(); latest_scans.extend(scans)
                if bot_enabled and not emergency_stop:
                    manage_sells(scans)
                    if not manual_override:
                        result = buy_best_stock(scans, manual=False)
                        if result: print(result)
                update_status(BOT_NAME, scans)
            time.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"Main loop error: {e}"); time.sleep(10)
