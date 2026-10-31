"""Static safety tests for stock no-buy diagnostics."""
import ast
from pathlib import Path

def test_no_buy_log_and_existing_guards():
    source = Path("backend/legacy/monolith.py").read_text()
    ast.parse(source)
    assert 'V19 STOCK NO-BUY AUDIT |' in source
    assert 'plan["status"], len(picks), order_limit' in source
    assert 'sorted(reason_counts.items())' in source
    assert 'MARA_DAILY_ENTRY_LIMIT = 1' in source
    assert '_v16_save_portfolio_plan(plan)' in source
