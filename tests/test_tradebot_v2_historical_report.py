from datetime import date, timedelta
import pytest
from backend.tradebot_v2 import historical_report


def fake_download(symbol, start, end, *, feed):
    assert feed == "iex"
    assert start == "2022-01-01"
    assert end == "2026-11-19"
    base = date(2022, 1, 1)
    return [historical_report.__import__("datetime").date(2022,1,1)]


def synthetic_rows(symbol, start, end, *, feed):
    from backend.tradebot_v2.backtest import DatedClose
    base = date(2022, 1, 1)
    return [DatedClose(base + timedelta(days=i), 100+i/20) for i in range(1500)]


def test_report_includes_all_seven_symbols_and_no_orders():
    result = historical_report.build_report(downloader=synthetic_rows)
    assert [x["symbol"] for x in result["results"]] == list(historical_report.SYMBOLS)
    assert result["execution_enabled"] is False
    assert result["orders_submitted"] == 0
    assert all(x["training_end"] == date(2024, 12, 31) for x in result["results"])
    assert "NOT a portfolio backtest" in result["method"]


def test_report_fails_whole_run_on_missing_data():
    def missing(symbol, start, end, *, feed):
        if symbol == "NVDA":
            raise ValueError("missing data")
        return synthetic_rows(symbol, start, end, feed=feed)
    with pytest.raises(ValueError, match="missing data"):
        historical_report.build_report(downloader=missing)
