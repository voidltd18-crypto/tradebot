from backend.low_profit_stock_review import low_profit_stock_review


def test_only_repeated_small_winners_are_candidates():
    rows = ([{"symbol": "FLNC", "qty": 1, "pnlGbp": p}
             for p in [2, -9, 4, -5, -2]] +
            [{"symbol": "MARA", "qty": 1, "pnlGbp": p}
             for p in [23.91, -1, 2, 3, -2]] +
            [{"symbol": "NEW", "qty": 1, "pnlGbp": p}
             for p in [-2, 1]])
    result = {r["symbol"]: r for r in low_profit_stock_review(rows)}
    assert result["FLNC"]["reviewForExclusion"] is True
    assert result["MARA"]["reviewForExclusion"] is False
    assert result["NEW"]["reviewForExclusion"] is False


def test_zero_quantity_and_invalid_rows_not_counted():
    rows = [{"symbol": "FLNC", "qty": 0, "pnlGbp": 0}] * 20
    rows += [{"symbol": "FLNC", "qty": 1, "pnlGbp": -1}]
    assert low_profit_stock_review(rows)[0]["closedTrades"] == 1
    assert low_profit_stock_review(rows)[0]["reviewForExclusion"] is False


def test_threshold_is_strictly_below_five_pounds():
    rows = [{"symbol": "ABC", "qty": 1, "pnlGbp": p} for p in [5, 1, -1, -1, 0]]
    assert low_profit_stock_review(rows)[0]["reviewForExclusion"] is False
