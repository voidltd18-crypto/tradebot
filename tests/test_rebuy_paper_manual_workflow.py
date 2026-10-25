from pathlib import Path


def test_manual_paper_workflow_is_not_automatic():
    source = Path(".github/workflows/manual-alpaca-paper-rebuy.yml").read_text()
    assert "workflow_dispatch:" in source
    assert "push:" not in source
    assert "schedule:" not in source
    assert "PAPER_ALPACA_API_KEY" in source
    assert "PAPER_ALPACA_SECRET_KEY" in source
    assert "'PAPER XRP $2'" in source
    assert "scripts/check_crypto_rebuy_paper.py --submit --symbol XRP/USD" in source
    assert "python scripts/check_crypto_rebuy_paper.py --symbol XRP/USD" in source
    assert "dry-run" in source
