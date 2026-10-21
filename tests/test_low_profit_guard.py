from backend.low_profit_guard import weak_symbols_by_realised_trades


def test_blocks_only_repeat_stocks_never_above_five_pounds():
    rows = [
        ("FLNC", "sell1", -9.50), ("FLNC", "sell2", 1.0), ("FLNC", "sell3", 4.99),
        ("MARA", "sell4", -2.0), ("MARA", "sell5", 23.91), ("MARA", "sell6", 1.0),
    ]
    weak = weak_symbols_by_realised_trades(rows)
    assert weak["FLNC"]["trades"] == 3
    assert "MARA" not in weak


def test_fewer_than_three_sells_not_blacklisted():
    assert weak_symbols_by_realised_trades([("ABC", "a", -10), ("ABC", "b", 1)]) == {}


def test_split_fifo_matches_should_be_preaggregated_by_sell_order():
    # Query groups FIFO rows by source sell order before reaching this helper.
    rows = [("ABC", "a", 4.0), ("ABC", "b", -2.0), ("ABC", "c", 3.0)]
    assert "ABC" in weak_symbols_by_realised_trades(rows)


def test_legacy_unknown_sell_orders_not_counted():
    rows = [("ABC", None, -20.0), ("ABC", "", 0), ("ABC", "a", -10)]
    assert weak_symbols_by_realised_trades(rows) == {}


def test_exactly_five_does_not_clear_filter():
    rows = [("XYZ", "a", 5.0), ("XYZ", "b", 1), ("XYZ", "c", -1)]
    assert "XYZ" in weak_symbols_by_realised_trades(rows)
