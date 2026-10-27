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

def test_manual_sell_has_broker_asset_type_split():
    import ast
    from pathlib import Path
    source = Path("backend/legacy/monolith.py").read_text()
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "market_sell_qty")
    code = ast.get_source_segment(source, fn)
    assert "TimeInForce.GTC if _manual_sell_is_crypto(symbol) else TimeInForce.DAY" in code


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
