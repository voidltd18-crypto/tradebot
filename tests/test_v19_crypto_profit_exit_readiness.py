from backend.v19_crypto_profit_exit_readiness import assess_profit_exit as check

BASE = dict(entry="100", quantity="10", bid="108", verified_peak="110",
            fee_rate="0.001", price_age_seconds=2, managed=True)

def test_net_profitable_trail_is_candidate_not_live_sell():
    out = check(**BASE)
    assert out["status"] == "candidate"
    assert out["action"] == "NO_ACTION"
    assert out["readyForExecution"] is False

def test_unmanaged_is_never_adopted():
    assert check(**{**BASE, "managed": False})["status"] == "blocked"

def test_loss_after_fees_and_slippage_is_blocked():
    out = check(**{**BASE, "bid": "100.1", "verified_peak": "110"})
    assert out["netProfitPositive"] is False

def test_missing_or_stale_bid_is_blocked():
    assert check(**{**BASE, "price_age_seconds": None})["status"] == "blocked"
    assert check(**{**BASE, "price_age_seconds": 35})["status"] == "blocked"

def test_pending_order_blocks():
    assert check(**{**BASE, "pending_sell": True})["status"] == "blocked"

def test_high_water_must_be_real_and_verified():
    assert check(**{**BASE, "verified_peak": None})["status"] == "blocked"

def test_no_trail_breach_means_hold():
    assert check(**{**BASE, "bid": "109.5"})["status"] == "blocked"

def test_invalid_cost_settings_fail_closed():
    for val in (None, "nan", "-0.1", "1.5"):
        assert check(**{**BASE, "fee_rate": val})["status"] == "blocked"
