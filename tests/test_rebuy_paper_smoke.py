import ast
from pathlib import Path


def test_paper_smoke_never_uses_live_credentials_or_live_api():
    source = Path("scripts/check_crypto_rebuy_paper.py").read_text()
    tree = ast.parse(source)
    assert 'PAPER_ALPACA_API_KEY' in source
    assert 'PAPER_ALPACA_SECRET_KEY' in source
    assert 'TradingClient(key, secret, paper=True)' in source
    assert 'TRADEBOT_ALPACA' not in source
    assert 'paper=False' not in source
    assert '--submit' in source
    assert any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in tree)


def test_missing_paper_credentials_never_submits(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("paper_test", "scripts/check_crypto_rebuy_paper.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("PAPER_ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("PAPER_ALPACA_SECRET_KEY", raising=False)
    assert module.main(["--submit"]) == 2
