from datetime import date, timedelta
import pytest

from backend.tradebot_v2 import backtest


def rows(n=90):
    start = date(2025, 1, 1)
    return [backtest.DatedClose(start + timedelta(days=i), 100 + i * .2) for i in range(n)]


def run(data=None, **kwargs):
    return backtest.evaluate_out_of_sample(
        "AAPL", data if data is not None else rows(),
        source="synthetic test fixture; not real market data",
        training_end=date(2025, 2, 15), **kwargs,
    )


def test_provenance_and_split_and_benchmark():
    result = run()
    assert result.source.startswith("synthetic")
    assert result.training_end == date(2025, 2, 15)
    assert result.benchmark_return_pct > 0
    assert result.test_signals == 0
    assert result.net_mean_return_pct is None


def test_fee_deducted_and_no_future_lookahead(monkeypatch):
    seen = []
    def green(symbol, closes):
        seen.append(len(closes))
        return type("Signal", (), {"status": "GREEN"})()
    monkeypatch.setattr(backtest, "evaluate_pullback", green)
    a = run(roundtrip_fee_bps=0)
    b = run(roundtrip_fee_bps=100)
    assert a.test_signals == b.test_signals > 0
    assert b.net_mean_return_pct == pytest.approx(a.net_mean_return_pct - 1)
    assert max(seen) <= len(rows()) - 5


@pytest.mark.parametrize("change", [
    lambda x: list(reversed(x)),
    lambda x: x[:5] + [x[4]] + x[5:],
    lambda x: x[:5] + [backtest.DatedClose(x[5].day, float("nan"))] + x[6:],
])
def test_invalid_prices_or_date_order_rejected(change):
    with pytest.raises(ValueError):
        run(change(rows()))


def test_no_unverified_provenance():
    with pytest.raises(ValueError):
        backtest.evaluate_out_of_sample(
            "AAPL", rows(), source=" ", training_end=date(2025, 2, 15)
        )


def test_rejects_short_training_window():
    with pytest.raises(ValueError):
        backtest.evaluate_out_of_sample(
            "AAPL", rows(), source="synthetic", training_end=date(2025, 1, 10)
        )


def test_does_not_claim_portfolio_performance():
    assert "not portfolio P&L" in run().warning
