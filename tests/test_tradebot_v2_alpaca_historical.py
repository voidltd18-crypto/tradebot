from datetime import date, timedelta
import pytest
from backend.tradebot_v2.alpaca_historical import parse_alpaca_daily_bars, evaluate_alpaca_export


def export(n=90):
    return {"bars": {"AAPL": [
        {"t": f"{date(2025,1,1)+timedelta(days=i)}T00:00:00Z", "c": 100+i/10}
        for i in range(n)
    ]}, "next_page_token": None}


def parse(payload=None, **kwargs):
    return parse_alpaca_daily_bars(
        export() if payload is None else payload, "AAPL",
        adjustment="all", timeframe="1Day", **kwargs,
    )


def test_adjusted_export_parses():
    assert len(parse()) == 90


def test_backtest_has_explicit_provenance():
    result = evaluate_alpaca_export("AAPL", export(), training_end=date(2025,2,15))
    assert "adjustment=all" in result.source


@pytest.mark.parametrize("payload", [
    {"bars": {"AAPL": []}},
    {"bars": {"AAPL": [{"t": "2025-01-01T00:00:00Z", "c": -1}]}},
    {"bars": {"AAPL": [{"t": "2025-01-01T00:00:00Z", "c": float("nan")}]}},
    {"bars": {"AAPL": [{"t": "2025-01-01T00:00:00Z", "c": 1},
                       {"t": "2025-01-01T00:00:00Z", "c": 2}]}},
    {"bars": {"AAPL": []}, "next_page_token": "more"},
])
def test_bad_or_incomplete_export_rejected(payload):
    with pytest.raises(ValueError):
        parse(payload)


def test_raw_bars_rejected():
    with pytest.raises(ValueError):
        parse_alpaca_daily_bars(export(), "AAPL", adjustment="raw", timeframe="1Day")


def test_intraday_bars_rejected():
    with pytest.raises(ValueError):
        parse_alpaca_daily_bars(export(), "AAPL", adjustment="all", timeframe="1Min")


def test_unapproved_symbol_rejected():
    with pytest.raises(ValueError):
        parse_alpaca_daily_bars(export(), "TSLA", adjustment="all", timeframe="1Day")
