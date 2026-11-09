"""Read-only refresh regressions: browser polling and broker-fill cache invalidation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "frontend" / "src" / "hooks" / "useTradeBot.ts"
MONOLITH = ROOT / "backend" / "legacy" / "monolith.py"


def test_reports_poll_only_while_reports_tab_visible():
    text = HOOK.read_text(encoding="utf-8")
    assert "const REPORTS_REFRESH_MS = 15000;" in text
    assert 'if (!authToken || activeTab !== "reports") return;' in text
    assert 'if (document.visibilityState === "visible") loadReports(false);' in text
    assert "window.clearInterval(timer)" in text


def test_reports_refresh_on_tab_resume_and_after_manual_action():
    text = HOOK.read_text(encoding="utf-8")
    assert 'document.addEventListener("visibilitychange", onVisible);' in text
    assert 'if (activeTab === "reports") loadReports(true);' in text
    assert 'if (activeTab === "reports") await loadReports(true);' in text
    assert "if (reportsInFlight.current || (!force &&" in text
    assert 'fetchJsonWithTimeout("/reports", 90000)' in text


def test_confirmed_broker_fill_invalidates_report_cache_not_on_submission():
    text = MONOLITH.read_text(encoding="utf-8")
    start = text.index("        rebuild_result = None")
    end = text.index("        # Apply realised sell PnL", start)
    sync_block = text[start:end]
    assert 'report_lock = globals().get("_reports_payload_lock")' in sync_block
    assert 'report_cache = globals().get("_reports_payload_cache")' in sync_block
    assert 'if report_lock is not None and isinstance(report_cache, dict):' in sync_block
    assert 'report_cache["at"] = 0.0' in sync_block
    assert 'report_cache["value"] = None' in sync_block
    assert 'rebuild_closed_trades_from_orders()' in sync_block
    assert "REPORTS_CACHE_SECONDS" in text
