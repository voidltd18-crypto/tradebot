from backend.v19_stock_account_gate_audit import locked_symbol_names

def test_only_daily_locked_tickers_are_reported():
    blocks = [("MARA", "MARA locked until tomorrow"),
              ("SOFI", "SOFI locked until tomorrow"),
              ("KO", "KO already holding"),
              ("SOFI", "SOFI locked until tomorrow"),
              ("BAD SECRET", "locked until tomorrow")]
    assert locked_symbol_names(blocks) == ["MARA", "SOFI"]

def test_empty_locks():
    assert locked_symbol_names([("KO", "KO existing open order")]) == []
