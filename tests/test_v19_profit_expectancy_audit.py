from backend.v19_profit_expectancy_audit import small_wins_audit


def test_small_wins_audit_does_not_confuse_win_frequency_with_profitability():
    trades = [
        {"symbol": "ABC", "qty": 1, "pnlGbp": 3.0},
        {"symbol": "ABC", "qty": 1, "pnlGbp": 4.0},
        {"symbol": "ABC", "qty": 1, "pnlGbp": -12.0},
        {"symbol": "ABC", "qty": 1, "pnlGbp": 2.0},
        {"symbol": "ABC", "qty": 1, "pnlGbp": -9.0},
        {"symbol": "XYZ", "qty": 0, "pnlGbp": 0.0},
    ]
    result = small_wins_audit(trades)
    assert result["excludedInvalidRows"] == 1
    abc = result["symbols"][0]
    assert abc["symbol"] == "ABC"
    assert abc["smallWins"] == 3
    assert abc["smallWinSharePct"] == 100
    assert abc["netRealisedGbp"] == -12.0
    assert abc["avgPnlPerTradeGbp"] == -2.4
    assert abc["evidenceSufficient"] is True
    assert result["readOnly"] is True
    assert "block" not in abc


def test_insufficient_history_does_not_mark_symbol_as_proven():
    result = small_wins_audit([{"symbol": "MARA", "qty": 3, "pnlGbp": 23.91}])
    assert result["symbols"][0]["evidenceSufficient"] is False
    assert result["symbols"][0]["smallWins"] == 0
