from backend.v19_manual_crypto_rebuy_signal import assess_manual_rebuy

def check(**changes):
    params = dict(last_filled_sell_price="6.49", current_ask="6.51",
                  sell_verified=True, quote_fresh=True)
    params.update(changes)
    return assess_manual_rebuy(**params)

def test_above_sale_wait():
    assert check()["status"] == "WAIT"

def test_three_percent_watch():
    assert check(current_ask="6.29")["status"] == "WATCH"

def test_five_percent_without_recovery_watch():
    assert check(current_ask="6.16")["status"] == "WATCH"

def test_recovery_candidate_never_orders():
    result = check(current_ask="6.16", recovery_confirmed=True)
    assert result["status"] == "BUY_CANDIDATE"
    assert result["readOnly"] and not result["orderSubmitted"]

def test_missing_broker_verification_blocks():
    assert check(sell_verified=False, current_ask="6.00", recovery_confirmed=True)["status"] == "WAIT"

def test_existing_position_blocks():
    assert check(current_ask="6.00", recovery_confirmed=True, position_open=True)["status"] == "WAIT"
