"""Offline regression: automatic crypto profit sell must check pause before reservation and submit."""
import ast
from pathlib import Path


def test_profit_seller_checks_persistent_pause_before_reserve_and_submit():
    tree = ast.parse(Path("backend/v19_crypto_profit_sell_executor.py").read_text())
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
              and n.name == "poll_profit_sells")
    source = ast.get_source_segment(Path("backend/v19_crypto_profit_sell_executor.py").read_text(), fn)
    assert source.count("if is_paused():") >= 2
    assert source.index("if is_paused():") < source.index("oid = _reserve(db_path, identity)")
    assert source.rindex("if is_paused():") < source.index("client.submit_order(")


def test_no_live_master_pause_wiring_on_main_branch():
    # This test only checks the development branch implementation.
    # Production deployment and restart are explicitly out of scope.
    assert Path("backend/v20_master_pause.py").exists()
