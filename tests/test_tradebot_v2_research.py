from backend.tradebot_v2.research import evaluate_history

def test_no_green_for_flat_prices():
    result = evaluate_history("AAPL", [100.0] * 50)
    assert result.green_signals == 0
    assert result.average_forward_5_bar_pct is None

def test_short_series_has_no_signals():
    result = evaluate_history("MSFT", [100.0] * 20)
    assert result.observations == 0
    assert result.evaluated_signals == 0

def test_forward_horizon_is_not_included_in_signal_inputs(monkeypatch):
    from backend.tradebot_v2 import research
    seen = []
    def spy(symbol, prices):
        seen.append(len(prices))
        return type("S", (), {"status": "GREEN"})()
    monkeypatch.setattr(research, "evaluate_pullback", spy)
    result = research.evaluate_history("NVDA", [100.0] * 40)
    assert seen == list(range(30, 41))
    assert result.green_signals == 11
    assert result.evaluated_signals == 6

def test_invalid_forward_horizon():
    import pytest
    with pytest.raises(ValueError):
        evaluate_history("AAPL", [100.0] * 40, 0)


def test_non_finite_prices_rejected():
    import pytest
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            evaluate_history("AAPL", [100.0] * 35 + [bad])
