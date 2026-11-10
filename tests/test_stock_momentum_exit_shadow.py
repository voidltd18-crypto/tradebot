import pytest

from backend.stock_momentum_exit_shadow import ExitSettings, assess_exit


def test_disabled_by_default_even_after_large_reversal():
    result = assess_exit(100, [100, 101, 103, 106, 108, 107])
    assert result["candidateExit"] is False
    assert result["readOnly"] is True
    assert result["reason"] == "disabled"


def test_insufficient_history_does_not_trigger():
    result = assess_exit(100, [100, 105, 104], enabled=True)
    assert result["candidateExit"] is False
    assert result["reason"] == "insufficient_samples"


def test_spike_detected_on_acceleration():
    result = assess_exit(100, [100, 100.5, 101, 103, 105], enabled=True)
    assert result["mode"] == "SPIKE"
    assert result["candidateExit"] is False


def test_trend_reversal_candidate_only_when_armed_and_profitable():
    result = assess_exit(100, [100, 101, 102, 103, 104, 103], enabled=True)
    assert result["mode"] == "TREND"
    assert result["candidateExit"] is True
    assert result["reason"] == "peak_reversal"


def test_falling_position_never_triggers_profit_exit():
    result = assess_exit(100, [100, 102, 103, 98, 97], enabled=True)
    assert result["candidateExit"] is False


def test_no_exit_on_continued_rise():
    result = assess_exit(100, [100, 101, 102, 103, 104, 105], enabled=True)
    assert result["candidateExit"] is False


@pytest.mark.parametrize("prices", [[], [100, 0], [100, float("nan")], [100, float("inf")]])
def test_invalid_prices_rejected(prices):
    with pytest.raises(ValueError):
        assess_exit(100, prices, enabled=True)


def test_threshold_validation():
    with pytest.raises(ValueError):
        ExitSettings(spike_trail_pct=0)


def test_cannot_submit_orders():
    result = assess_exit(100, [100, 101, 102, 103, 104, 103], enabled=True)
    assert "order" not in result
    assert result["existingRiskControlsRequired"] is True
