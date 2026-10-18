"""V19 read-only research-memory inventory.

Run: python tests/test_v19_research_memory_inventory.py
This intentionally parses source instead of importing the live trading application.
No broker credentials, network requests, database writes or order actions.
"""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
TARGETS = (
    "locked_universe_runtime_cache",
    "adaptive_universe_runtime_cache",
    "latest_scans",
    "trade_history",
    "stock_memory",
    "trade_events",
    "equity_curve",
)

def inventory():
    found = {}
    for node in TREE.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            names = [node.target.id] if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) else [
                target.id for target in getattr(node, "targets", []) if isinstance(target, ast.Name)
            ]
            for name in names:
                if name in TARGETS:
                    found[name] = {"line": node.lineno, "initialiser": type(node.value).__name__}
    return found

def test_memory_inventory_is_complete():
    found = inventory()
    assert set(found) == set(TARGETS), f"Missing state collections: {set(TARGETS) - set(found)}"
    assert len(found) == len(TARGETS)

def test_inventory_does_not_import_trading_application():
    source = Path(__file__).read_text(encoding="utf-8")
    assert "import backend.legacy.monolith" not in source
    assert "from backend.legacy import monolith" not in source
    assert "submit_order(" not in source

if __name__ == "__main__":
    test_memory_inventory_is_complete()
    test_inventory_does_not_import_trading_application()
    for name, metadata in inventory().items():
        print(f"V19 MEMORY INVENTORY | name={name} line={metadata['line']} initialiser={metadata['initialiser']}")
    print("V19 research-memory inventory checks passed")
