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
    # Inspect executable syntax, not text: literal forbidden strings in assertions
    # would otherwise match themselves and make this check fail unconditionally.
    test_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(test_tree):
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("backend.legacy") for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("backend.legacy")
        elif isinstance(node, ast.Call):
            called = node.func
            assert not (isinstance(called, ast.Name) and called.id == "submit_order")
            assert not (isinstance(called, ast.Attribute) and called.attr == "submit_order")


def references():
    """Find direct collection references and common in-place mutations, statically."""
    found = {name: {"readers": set(), "writers": set()} for name in TARGETS}
    for node in ast.walk(TREE):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and child.id in found:
                kind = "writers" if isinstance(child.ctx, (ast.Store, ast.Del)) else "readers"
                found[child.id][kind].add(node.name)
            if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
                owner = child.func.value
                if isinstance(owner, ast.Name) and owner.id in found and child.func.attr in {
                    "append", "extend", "insert", "pop", "clear", "update", "setdefault", "remove", "sort", "reverse"
                }:
                    found[owner.id]["writers"].add(node.name)
            if isinstance(child, (ast.Assign, ast.AugAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name) and target.value.id in found:
                        found[target.value.id]["writers"].add(node.name)
    return {name: {kind: sorted(values) for kind, values in uses.items()} for name, uses in found.items()}

def test_reference_report_covers_all_collections():
    report = references()
    assert set(report) == set(TARGETS)
    assert all(isinstance(item["readers"], list) and isinstance(item["writers"], list) for item in report.values())

if __name__ == "__main__":
    test_memory_inventory_is_complete()
    test_inventory_does_not_import_trading_application()
    test_reference_report_covers_all_collections()
    for name, metadata in inventory().items():
        print(f"V19 MEMORY INVENTORY | name={name} line={metadata['line']} initialiser={metadata['initialiser']}")
    for name, uses in references().items():
        print(f"V19 MEMORY REFERENCES | name={name} readers={len(uses['readers'])} writers={len(uses['writers'])}")
    print("V19 research-memory inventory checks passed")
