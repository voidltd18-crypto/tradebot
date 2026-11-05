"""In-memory broker simulation of production stock buy + sell paths.

No Alpaca credentials, HTTP calls, imported live app, persistent DB, or orders.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import patch

from backend.v19_two_stock_asset_preflight import check_asset

SOURCE = Path("backend/legacy/monolith.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def isolated_function(name, env):
    fn = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == name)
    code = ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))
    exec(compile(code, "isolated_monolith", "exec"), env)
    return env[name]


class PaperBroker:
    def __init__(self):
        self.orders = []
    def get_asset(self, symbol):
        return SimpleNamespace(
            symbol=symbol,
            name={"TSLA": "Tesla Inc. Common Stock",
                  "SPCX": "Space Exploration Technologies Corp. Class A Common Stock"}[symbol],
            asset_class="us_equity", status="active", tradable=True, fractionable=True,
        )
    def submit_order(self, request):
        self.orders.append(request)
        return SimpleNamespace(id="SIMULATED-ORDER", status="pending_new")


def environment(broker, *, paused):
    events = []
    persisted_sells = []
    locks = []
    env = {
        "Optional": Optional, "Dict": Dict, "Any": Any,
        "TRADEBOT_STOCK_BUYS_PAUSED": paused,
        "TRADEBOT_TWO_STOCK_MODE": True,
        "TRADEBOT_TWO_STOCK_SYMBOLS": ("TSLA", "SPCX"),
        "trading_client": broker,
        "two_stock_buy_allowed": lambda symbol: symbol in ("TSLA", "SPCX"),
        "low_profit_buy_allowed": lambda symbol: (True, ""),
        "MarketOrderRequest": lambda **kwargs: kwargs,
        "OrderSide": SimpleNamespace(BUY="BUY", SELL="SELL"),
        "TimeInForce": SimpleNamespace(DAY="DAY", GTC="GTC"),
        "AI_RISK_ENGINE_ENABLED": False,
        "trade_events": events,
        "add_trade_history_event": lambda event: None,
        "today_str": lambda: "2026-11-05",
        "now_time": lambda: "15:00:00",
        "money_gbp": lambda amount: amount,
        "notify": lambda message: None,
        "floor_qty": lambda value, precision: round(value, precision),
        "_manual_sell_is_crypto": lambda symbol: False,
        "register_pending_sell_order": lambda *args: persisted_sells.append(args) or True,
        "lock_symbol_until_tomorrow": lambda symbol: locks.append(symbol),
        "is_insufficient_qty_error": lambda error: False,
        "add_alpaca_rejection_event": lambda *args: None,
    }
    return env, events, persisted_sells, locks


def test_simulated_tesla_spacex_buy_sell_acknowledgement_not_fill():
    for symbol in ("TSLA", "SPCX"):
        broker = PaperBroker()
        assert check_asset(symbol, broker.get_asset(symbol))["eligible"]
        env, events, pending, locks = environment(broker, paused=False)
        buy = isolated_function("market_buy_notional", env)
        sell = isolated_function("market_sell_qty", env)

        buy(symbol, 100.00, reason="SIMULATED AUTO BUY")
        assert len(broker.orders) == 1
        assert broker.orders[0]["symbol"] == symbol
        assert broker.orders[0]["side"] == "BUY"
        assert broker.orders[0]["notional"] == 100.0
        sell(symbol, 0.25, entry=100, price=102, reason="SIMULATED SELL")
        assert len(broker.orders) == 2
        assert broker.orders[1]["side"] == "SELL"
        assert broker.orders[1]["time_in_force"] == "DAY"
        assert pending and locks == [symbol]
        assert events[-1]["accountingStatus"] == "PENDING_FILL_RECONCILIATION"
        assert "pnl" not in events[-1]
        assert events[-1]["estimatedPnl"] == 0.5


def test_simulated_buy_pause_blocks_tesla_spacex_and_old_stocks():
    for symbol in ("TSLA", "SPCX", "MARA", "UVXY"):
        broker = PaperBroker()
        env, _, _, _ = environment(broker, paused=True)
        buy = isolated_function("market_buy_notional", env)
        try:
            buy(symbol, 100)
        except ValueError as error:
            assert "stock buys paused" in str(error)
        else:
            raise AssertionError("A paused buy reached the broker")
        assert broker.orders == []


def test_live_guard_keeps_other_tickers_out_after_unpause():
    broker = PaperBroker()
    env, _, _, _ = environment(broker, paused=False)
    buy = isolated_function("market_buy_notional", env)
    for symbol in ("MARA", "UVXY"):
        try:
            buy(symbol, 100)
        except ValueError as error:
            assert "two-stock" in str(error)
        else:
            raise AssertionError("Wrong stock accepted")
    assert broker.orders == []
