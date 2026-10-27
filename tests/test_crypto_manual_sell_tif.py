from pathlib import Path

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
