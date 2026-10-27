from datetime import datetime, timedelta, timezone
from backend.v19_crypto_repeat_cycle import assess_crypto_dip_entry

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)

def evaluate(symbol="UNIUSD", **overrides):
    args = dict(symbol=symbol, ask="6.95", ask_at=NOW, positions=[],
                open_order_symbols=[], available_cash="1000", spend_usd="100",
                last_sale_price="7.00", last_sale_at=NOW - timedelta(minutes=31),
                last_sale_filled=True, now=NOW)
    args.update(overrides)
    return assess_crypto_dip_entry(**args)

def test_universal_dip_after_confirmed_sale():
    assert evaluate("UNIUSD")["canEnter"] is True
    assert evaluate("BTCUSD", ask="69000", last_sale_price="70000")["canEnter"] is True
    assert evaluate("SOLUSD", ask="6.95", last_sale_price="7.00")["canEnter"] is True

def test_never_dip_buy_held_pending_or_unverified():
    assert not evaluate(positions=["UNI/USD"])["canEnter"]
    assert not evaluate(open_order_symbols=["UNIUSD"])["canEnter"]
    assert not evaluate(last_sale_filled=False)["canEnter"]
    assert not evaluate(last_sale_at=NOW - timedelta(minutes=5))["canEnter"]
    assert not evaluate(ask_at=NOW - timedelta(minutes=5))["canEnter"]
    assert not evaluate(symbol="NOT/GBP")["canEnter"]


def test_worker_is_opt_in_and_coin_scoped():
    import ast
    from pathlib import Path
    source = Path("backend/v19_universal_crypto_cycle_executor.py").read_text()
    ast.parse(source)
    assert "TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_LIVE_APPROVED" in source
    assert "TRADEBOT_UNIVERSAL_CRYPTO_CYCLE_SYMBOLS" in source
    assert "symbol=sym" in source
    assert 'approved.discard("XRPUSD")' in source
    assert 'str(getattr(order, "client_order_id", "")).startswith("tbprofit-")' in source
    assert "TimeInForce.GTC" in source


def test_sell_order_time_in_force_simulated_without_broker():
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    source = Path("backend/legacy/monolith.py").read_text()
    parsed = ast.parse(source)
    chosen = [n for n in parsed.body if isinstance(n, ast.FunctionDef)
              and n.name in ("_manual_sell_is_crypto", "market_sell_qty")]
    assert len(chosen) == 2
    submitted = []
    class OrderRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
    class Broker:
        def __init__(self, asset_class):
            self.asset_class = asset_class
        def get_asset(self, symbol):
            return SimpleNamespace(asset_class=self.asset_class)
        def submit_order(self, order):
            submitted.append(order)
            return SimpleNamespace(id="paper-order", status="accepted")
    env = {
        "trading_client": Broker("crypto"),
        "MarketOrderRequest": OrderRequest,
        "OrderSide": SimpleNamespace(SELL="sell"),
        "TimeInForce": SimpleNamespace(GTC="gtc", DAY="day"),
        "floor_qty": lambda qty, precision: qty,
        "register_pending_sell_order": lambda *args: True,
        "today_str": lambda: "2026-10-27",
        "now_time": lambda: "12:00",
        "money_gbp": lambda value: value,
        "trade_events": [],
        "lock_symbol_until_tomorrow": lambda symbol: None,
        "notify": lambda value: None,
    }
    exec(compile(ast.Module(body=chosen, type_ignores=[]), "isolated_sell.py", "exec"), env)
    env["market_sell_qty"]("UNIUSD", 1.2, entry=7, price=7.2)
    assert submitted[-1].time_in_force == "gtc"
    env["trading_client"] = Broker("us_equity")
    env["market_sell_qty"]("AAPL", 1, entry=100, price=102)
    assert submitted[-1].time_in_force == "day"
