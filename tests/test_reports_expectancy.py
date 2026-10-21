from backend.reports_expectancy import recent_trade_expectancy


def test_recent_trade_expectancy_exposes_reward_risk_gap():
    result = recent_trade_expectancy([
        {"qty": 1, "pnlGbp": 5},
        {"qty": 1, "pnlGbp": 5},
        {"qty": 1, "pnlGbp": -10},
        {"qty": 0, "pnlGbp": -500},
    ])
    assert result["sampleTrades"] == 3
    assert result["netRealisedGbp"] == 0
    assert result["averageWinnerGbp"] == 5
    assert result["averageLoserGbp"] == 10
    assert result["breakEvenWinRatePct"] == 66.67
    assert result["profitFactor"] == 1
    assert result["readOnly"] is True


def test_bad_or_missing_records_do_not_inflate_performance():
    result = recent_trade_expectancy([
        {"qty": "bad", "pnlGbp": 100},
        {"qty": 2, "pnlGbp": "nan"},
        {"qty": 0, "pnlGbp": 20},
    ])
    assert result["sampleTrades"] == 0
    assert result["breakEvenWinRatePct"] is None
