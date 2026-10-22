"""Static regression checks for modest adaptive universe expansion."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"

def test_adaptive_defaults_and_overrides():
    src = SOURCE.read_text()
    ast.parse(src)
    assert 'os.getenv("ADAPTIVE_UNIVERSE_TARGET_SIZE", "18")' in src
    assert 'os.getenv("ADAPTIVE_UNIVERSE_DISCOVERY_SLOTS", "12")' in src
    assert 'os.getenv("ADAPTIVE_UNIVERSE_CORE_SLOTS", "4")' in src

def test_stock_entry_gates_still_present():
    src = SOURCE.read_text()
    assert "def v17_live_entry_gate_pipeline(" in src
    assert 'if not reputation_ok:' in src
    assert 'if not sniper_ok:' in src
    assert 'if not aplus_ok:' in src
    assert 'if not v2_ok:' in src
    assert "QUALITY_BELOW_MINIMUM" in src
