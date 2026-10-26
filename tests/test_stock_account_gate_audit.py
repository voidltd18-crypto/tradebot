from backend.v19_stock_account_gate_audit import account_block_category, account_block_summary


def test_classifies_broker_safety_rejections():
    examples = {
        "MARA locked until tomorrow (MARA daily entries 1/1)": "mara_daily_limit",
        "NVDA locked until tomorrow": "daily_lock",
        "KO existing open order": "open_order",
        "AAPL already holding": "already_holding",
        "repeat-low-profit stock": "low_profit_guard",
        "unfamiliar private broker reason": "other_account_block",
    }
    for reason, category in examples.items():
        assert account_block_category(reason) == category


def test_summary_never_emits_raw_reasons_or_changes_inputs():
    original = [("MARA", "MARA locked until tomorrow (MARA daily entries 1/1)"),
                ("KO", "KO existing open order"),
                ("ABC", "secret broker response")]
    copy = list(original)
    result = account_block_summary(original)
    assert result["total"] == 3
    assert result["reasons"] == {"mara_daily_limit": 1, "open_order": 1,
                                 "other_account_block": 1}
    assert "secret" not in result["summary"]
    assert original == copy


from backend.v19_stock_account_gate_audit import account_block_details


def test_details_show_symbols_and_safe_categories_only():
    blocks = [
        ("KO", "KO existing open order"),
        ("MARA", "MARA locked until tomorrow (MARA daily entries 1/1)"),
        ("WULF", "secret broker failure token=private"),
        ("bad symbol / text", "already holding"),
    ]
    unchanged = list(blocks)
    details = account_block_details(blocks)
    assert details == [
        {"symbol": "KO", "category": "open_order"},
        {"symbol": "MARA", "category": "mara_daily_limit"},
        {"symbol": "WULF", "category": "other_account_block"},
        {"symbol": "UNKNOWN", "category": "already_holding"},
    ]
    assert "private" not in repr(details)
    assert blocks == unchanged
