"""Guard the Telegram alert cadence without changing trading behavior."""
import ast
from pathlib import Path


def test_telegram_monitor_runs_every_sixty_seconds():
    path = Path("backend/v19_crypto_telegram_monitor.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    interval = next(n for n in tree.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == "INTERVAL" for t in n.targets))
    assert isinstance(interval.value, ast.Constant)
    assert interval.value.value == 60


def test_telegram_monitor_is_read_only_and_keeps_deduplication():
    source = Path("backend/v19_crypto_telegram_monitor.py").read_text(encoding="utf-8")
    assert "v19_telegram_seen" in source
    assert "INSERT OR IGNORE INTO v19_telegram_seen" in source
    assert "get_all_positions()" in source
    assert "get_orders(" in source
    assert "submit_order(" not in source
    assert "close_position(" not in source
    assert "time.sleep(INTERVAL)" in source
