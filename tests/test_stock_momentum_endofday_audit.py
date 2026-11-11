from datetime import datetime, timedelta, timezone
from backend.stock_momentum_endofday_audit import full_session_comparison


def rows(prices):
    start = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
    return [{"timestamp": (start + timedelta(minutes=i)).isoformat(), "price": p}
            for i, p in enumerate(prices)]


def test_no_signal_has_explicit_assumed_close_not_proven_trade():
    report = full_session_comparison(100, rows([100, 99, 98, 97, 96]))
    assert report["candidate"]["status"] == "ASSUMED_LAST_BAR_LIQUIDATION"
    assert report["reference"]["status"] == "ASSUMED_LAST_BAR_LIQUIDATION"
    assert report["candidate"]["netReturnPct"] < 0
    assert report["candidateMinusReferenceUsd"] == 0
    assert not report["releaseReady"]
    assert report["ordersSubmitted"] == 0


def test_actual_signal_compared_with_same_costs():
    prices = [100, 100.3, 101, 102, 103, 102.4, 102.2, 101.9]
    report = full_session_comparison(100, rows(prices))
    assert report["candidate"]["status"] == "SIMULATED_PROFIT_EXIT"
    assert report["reference"]["status"] == "SIMULATED_PROFIT_EXIT"


def test_unfillable_signal_is_not_silently_imputed():
    prices = [100, 100.3, 101, 102, 103, 102.4]
    report = full_session_comparison(100, rows(prices))
    assert report["candidate"]["status"] == "NO_NEXT_QUOTE"
    assert report["candidate"]["netPnlUsd"] is None
    assert report["candidateMinusReferenceUsd"] is None
