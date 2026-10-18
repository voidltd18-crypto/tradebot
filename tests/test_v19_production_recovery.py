"""Non-trading V19 checks for production-based historical outcome recovery."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"
text = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(text)

def body(name):
    fn = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ast.get_source_segment(text, fn)

def test_historical_lookup_separate_from_write():
    writer = body("_v6_write_historical_outcome")
    evaluator = body("v2_evaluate_due_outcomes")
    assert "if checkpoint is None:" in writer
    assert "checkpoint_data = _v6_historical_checkpoint_price(" in evaluator
    assert evaluator.index("checkpoint_data = _v6_historical_checkpoint_price(") < evaluator.index("_v6_write_historical_outcome(conn,row,checkpoint_data)")
    assert "conn.rollback()" in evaluator
    assert "conn.commit()" in evaluator

def test_live_accounting_and_mara_guards_preserved():
    assert "MARA_DAILY_ENTRY_LIMIT" in text
    assert "FIRST_DIBS_ENABLED" in text
    assert "_release_transient_memory" in text

def test_mara_single_entry_and_sell_lock():
    buy = body("can_buy_symbol")
    locked = body("is_locked_today")
    assert "today_symbol_buy_count(sym) >= MARA_DAILY_ENTRY_LIMIT" in buy
    assert "today_symbol_buy_count(sym) >= 1" in locked
    assert "MARA_DAILY_ENTRY_LIMIT = 1" in text


def test_memory_instrumentation_is_read_only():
    probe = body("_v19_process_rss_mb")
    cleanup = body("_release_transient_memory")
    assert '"/proc/self/status"' in probe
    assert 'line.startswith("VmRSS:")' in probe
    assert "rss_before_mb = _v19_process_rss_mb()" in cleanup
    assert "rss_after_mb = _v19_process_rss_mb()" in cleanup
    assert cleanup.index("rss_before_mb =") < cleanup.index("gc.collect()") < cleanup.index("rss_after_mb =")
    assert "submit_order" not in cleanup
    assert "market_sell" not in cleanup


def test_sampled_memory_diagnostics_have_no_trading_side_effects():
    fn = body("_v19_memory_snapshot")
    assert "gc.get_count()" in fn
    assert "_v19_process_rss_mb()" in fn
    assert "_V19_MEMORY_SAMPLE_EVERY" in fn
    assert "submit_order" not in fn
    assert "db_connect" not in fn
    assert "_v19_memory_snapshot(reason)" in body("_release_transient_memory")


def test_scanner_memory_probe_preserves_candidate_selection():
    scanner = body("refresh_dynamic_market_candidates")
    assert "_v19_scanner_rss_start = _v19_process_rss_mb()" in scanner
    assert "_v19_scanner_rss_end = _v19_process_rss_mb()" in scanner
    assert "V19 SCANNER MEMORY" in scanner
    assert "saved_payload = _save_dynamic_scanner_cache(payload)" in scanner
    assert "return saved_payload" in scanner


def test_scanner_reuses_readonly_cache_containers():
    scanner = body("refresh_dynamic_market_candidates")
    assert "prior_cache = _load_dynamic_scanner_cache() or {}" in scanner
    assert 'prior_rows = prior_cache.get("rows") or []' in scanner
    assert "dict(_load_dynamic_scanner_cache()" not in scanner
    assert 'rows = prior_rows[:DYNAMIC_MARKET_SCANNER_MAX_SYMBOLS]' in scanner
    assert "rows_by_symbol: Dict[str, Dict[str, Any]] = {}" in scanner


if __name__ == "__main__":
    test_historical_lookup_separate_from_write()
    test_live_accounting_and_mara_guards_preserved()
    test_mara_single_entry_and_sell_lock()
    test_memory_instrumentation_is_read_only()
    test_sampled_memory_diagnostics_have_no_trading_side_effects()
    test_scanner_memory_probe_preserves_candidate_selection()
    test_scanner_reuses_readonly_cache_containers()
    print("V19 production-based checks passed")
