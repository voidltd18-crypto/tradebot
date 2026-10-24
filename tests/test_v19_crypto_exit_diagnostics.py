from backend.v19_crypto_exit_diagnostics import crypto_exit_diagnostic as review


def test_external_sol_detected_but_never_sold():
    result = review("SOLUSD", "10.1713", "101.76", "101.80", "101.80")
    assert result["status"] == "observed"
    assert result["externalPosition"] is True
    assert result["eligibleForFutureOptIn"] is False
    assert result["trailStartPrice"] == "102.7776"
    assert result["action"] == "NO_ACTION"
    assert not result["sellOrderSubmitted"]


def test_weekend_stop_is_visible_without_market_open_requirement():
    result = review("SOLUSD", 10, 100, 94, 101)
    assert result["condition"] == "STOP_LOSS_CONDITION"
    assert result["action"] == "NO_ACTION"


def test_trailing_exit_triggered_from_prior_peak():
    result = review("SOLUSD", 1, 100, 102, 105)
    assert result["trailArmed"]
    assert result["condition"] == "TRAIL_CONDITION"
    assert result["action"] == "NO_ACTION"


def test_managed_external_still_diagnostic_only():
    result = review("SOLUSD", 1, 100, 105, 105, manage_external=True)
    assert result["eligibleForFutureOptIn"]
    assert result["action"] == "NO_ACTION"


def test_invalid_input_fails_closed():
    for price, peak in [(0, 100), (-5, 100), (101, 100), (float("nan"), 100)]:
        result = review("SOLUSD", 1, 100, price, peak)
        assert result["action"] == "NO_ACTION"
        assert result["status"] == "unverified"


def test_stock_symbol_not_implicitly_included():
    result = review("MARA", 1, 10, 9, 10)
    assert result["status"] == "unsupported"
    assert result["action"] == "NO_ACTION"
