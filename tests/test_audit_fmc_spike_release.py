"""End-to-end rehearsal never allows unearned production readiness."""
from scripts.audit_fmc_spike_release import release_audit
from backend.stock_momentum_cost_model import CostAssumptions


def csv_fixture(tmp_path):
    file = tmp_path / "fmc.csv"
    prices = [100, 100.3, 101, 102, 103, 102.4, 102.2, 101.9]
    lines = ["timestamp,close"]
    lines.extend(
        f"2026-11-09T14:{30 + i // 6:02d}:{(i % 6)*10:02d}Z,{p}"
        for i, p in enumerate(prices)
    )
    file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return file


def test_complete_local_audit_never_clears_live_release(tmp_path):
    result = release_audit(
        csv_fixture(tmp_path), source="synthetic test prices", entry_price=100,
        assumptions=CostAssumptions(spread_bps=20, exit_slippage_bps=15),
    )
    assert result["ordersSubmitted"] == 0
    assert not result["releaseReady"]
    assert not result["evidence"]["independentlyVerifiedHistoricalQuotes"]
    assert result["candidateExitSimulation"]["status"] == "SIMULATED_FILL"
    assert len(result["blockingReasons"]) >= 3


class FakePaper:
    def confirm_paper_account(self):
        return {"paperOnly": True, "accountIdPresent": True,
                "accountStatus": "ACTIVE", "ordersSubmitted": 0}


def test_paper_account_read_alone_is_not_paper_execution(tmp_path):
    result = release_audit(
        csv_fixture(tmp_path), source="operator label", entry_price=100,
        paper_reader=FakePaper(),
    )
    assert result["evidence"]["paperAccountRead"]["checked"]
    assert not result["evidence"]["actualPaperSellFillVerified"]
    assert not result["releaseReady"]


def test_higher_costs_lower_simulated_result(tmp_path):
    path = csv_fixture(tmp_path)
    low = release_audit(
        path, source="synthetic", entry_price=100,
        assumptions=CostAssumptions(spread_bps=5, exit_slippage_bps=5),
    )
    high = release_audit(
        path, source="synthetic", entry_price=100,
        assumptions=CostAssumptions(spread_bps=100, exit_slippage_bps=100),
    )
    assert high["candidateExitSimulation"]["netPnlUsd"] < low["candidateExitSimulation"]["netPnlUsd"]
