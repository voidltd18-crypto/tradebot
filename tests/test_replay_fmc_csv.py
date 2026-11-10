import pytest

from scripts.replay_fmc_csv import load_bars_csv, run_csv_replay


def test_offline_import_and_provenance(tmp_path):
    csv_path = tmp_path / "fmc.csv"
    csv_path.write_text(
        "timestamp,close\n"
        "2026-11-10T14:30:00Z,100\n"
        "2026-11-10T14:30:10Z,100.3\n"
        "2026-11-10T14:30:20Z,101\n"
        "2026-11-10T14:30:30Z,102\n"
        "2026-11-10T14:30:40Z,103\n"
        "2026-11-10T14:30:50Z,102.4\n"
        "2026-11-10T14:31:00Z,102.2\n"
        "2026-11-10T14:31:10Z,101.9\n",
        encoding="utf-8",
    )
    data = run_csv_replay(csv_path, symbol="FMC", source="synthetic test data", entry_price=100)
    assert data["candidate"]["status"] == "SIMULATED_FILL"
    assert data["dataVerifiedAsFmcHistory"] is False
    assert data["sourceDescription"] == "synthetic test data"
    assert data["ordersSubmitted"] == 0


def test_reject_non_fmc_and_no_provenance(tmp_path):
    csv_path = tmp_path / "bars.csv"
    csv_path.write_text("timestamp,close\n2026-11-10T14:30:00Z,100\n")
    with pytest.raises(ValueError):
        run_csv_replay(csv_path, symbol="GOOG", source="source", entry_price=100)
    with pytest.raises(ValueError):
        run_csv_replay(csv_path, symbol="FMC", source="", entry_price=100)


def test_missing_columns_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("date,last\n2026-11-10,100\n")
    with pytest.raises(ValueError):
        load_bars_csv(path)
