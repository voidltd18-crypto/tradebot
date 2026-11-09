"""The paper fill verifier must never place an order by default."""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_two_stock_paper_fill.py"

def test_default_is_no_order():
    proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert "DRY RUN" in proc.stdout

def test_missing_explicit_confirmation_is_no_order():
    proc = subprocess.run([sys.executable, str(SCRIPT), "--execute-paper"], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert "DRY RUN" in proc.stdout

def test_missing_paper_keys_is_blocked(monkeypatch):
    monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
    proc = subprocess.run([sys.executable, str(SCRIPT), "--execute-paper", "--confirm", "PAPER-ONLY"],
        capture_output=True, text=True, timeout=10, env={
            k:v for k,v in __import__("os").environ.items()
            if k not in {"ALPACA_PAPER_API_KEY", "ALPACA_PAPER_API_SECRET"}
        })
    assert proc.returncode == 2
    assert "BLOCKED" in proc.stderr
