from backend.v19_crypto_exit_diagnostics import crypto_exit_diagnostic as review


def test_external_sol_detected_but_never_sold():
    result = review("SOLUSD", "10.1713", "101.76", "101.80", "101.80")
    assert result["status"] == "observed"
    assert result["externalPosition"] is True
    assert result["eligibleForFutureOptIn"] is False
    assert result["trailStartPrice"] == "102.7776"
    assert result["action"] == "NO_ACTION"
    assert not result["sellOrderSubmitted"]


def test_weekend_loss_is_manual_only_without_market_open_requirement():
    result = review("SOLUSD", 10, 100, 94, 101)
    assert result["condition"] == "HOLD_LOSS_MANUAL_ONLY"
    assert result["automaticStopLossEnabled"] is False
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


def test_break_even_never_requests_automatic_exit():
    result = review("SOLUSD", 1, 100, 100, 110)
    assert result["condition"] == "HOLD_BREAK_EVEN_MANUAL_ONLY"
    assert not result["grossProfitPositive"]
    assert result["action"] == "NO_ACTION"


def test_trail_breach_below_entry_stays_manual_only():
    result = review("SOLUSD", 1, 100, 98, 120, manage_external=True)
    assert result["trailArmed"]
    assert result["condition"] == "HOLD_LOSS_MANUAL_ONLY"
    assert result["action"] == "NO_ACTION"


def test_trail_breach_still_positive_is_candidate_only():
    result = review("SOLUSD", 1, 100, 103, 110, manage_external=True)
    assert result["condition"] == "TRAIL_CONDITION"
    assert result["grossProfitPositive"]
    assert result["sellOrderSubmitted"] is False
