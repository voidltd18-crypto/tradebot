from datetime import datetime, timezone, timedelta
from backend.v19_crypto_observed_peaks import observe_position_peak


def test_peak_persists_over_observations_and_never_claims_since_entry(tmp_path):
    path = str(tmp_path / "trades.sqlite")
    date = datetime(2026, 10, 25, tzinfo=timezone.utc)
    def record(price, quantity="10"):
        return observe_position_peak(path, symbol="XRPUSD", entry="1.2",
                                     quantity=quantity, observed_price=price, observed_at=date)
    first = record("1.3")
    assert first["observedPeak"] == "1.3"
    assert first["observations"] == 1
    assert first["verifiedSinceEntry"] is False
    assert first["eligibleForAutomaticExit"] is False
    assert first["executableBid"] is False
    second = record("1.2")
    assert second["observedPeak"] == "1.3"
    assert second["observations"] == 2
    assert record("1.4")["observedPeak"] == "1.4"
    assert record("1.1", quantity="9")["observedPeak"] == "1.1"
    assert record("1.2")["observedPeak"] == "1.4"


def test_invalid_observations_are_rejected(tmp_path):
    path = str(tmp_path / "trades.sqlite")
    defaults = dict(symbol="SOLUSD", entry="100", quantity="10", observed_price="110")
    assert observe_position_peak(path, **{**defaults, "observed_price": "nan"})["status"] == "unverified"
    assert observe_position_peak(path, **{**defaults, "observed_at": datetime(2026, 10, 25)})["status"] == "unverified"
    assert observe_position_peak(path, **{**defaults, "symbol": "MARA"})["status"] == "unverified"
