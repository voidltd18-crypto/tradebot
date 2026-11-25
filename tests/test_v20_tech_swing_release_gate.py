import pytest
from backend.v20_tech_swing_release_gate import assess_release


def sample():
    return {"readOnly": True, "ordersSubmitted": 0, "totalReturnPct": 14.05,
            "maxDrawdownPct": -6.46, "matchedPassiveBasketReturnPct": 30.59,
            "matchedPassiveBasketDrawdownPct": -10.53,
            "freshCapital2026": {"returnPct": 3.72}}


def test_underperforming_strategy_cannot_pass():
    r = assess_release(sample(), forward_sessions=120, broker_guards_verified=True)
    assert not r["eligibleForLiveReview"]
    assert not r["liveOrdersAuthorized"] and r["ordersSubmitted"] == 0
    assert not r["checks"]["beats_matched_passive_return"]


def test_forward_validation_required():
    d = sample()
    d["totalReturnPct"] = 40
    assert not assess_release(d, broker_guards_verified=True)["eligibleForLiveReview"]


def test_rejects_untrusted_result():
    d = sample()
    d["ordersSubmitted"] = 1
    with pytest.raises(ValueError):
        assess_release(d)
