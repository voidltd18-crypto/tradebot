"""Retire MARA First Dibs without weakening stock trade protections."""
import ast
from pathlib import Path

SOURCE=Path("backend/legacy/monolith.py")

def test_first_dibs_disabled_even_when_environment_is_set():
    source=SOURCE.read_text()
    tree=ast.parse(source)
    assignments=[n for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=="FIRST_DIBS_ENABLED" for t in n.targets)]
    assert len(assignments)==1
    assert isinstance(assignments[0].value,ast.Constant)
    assert assignments[0].value.value is False

def test_mara_one_entry_limit_unchanged():
    source=SOURCE.read_text()
    tree=ast.parse(source)
    assignments=[n for n in tree.body if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=="MARA_DAILY_ENTRY_LIMIT" for t in n.targets)]
    assert len(assignments)==1
    assert isinstance(assignments[0].value,ast.Constant)
    assert assignments[0].value.value==1
    assert "if sym == \"MARA\" and today_symbol_buy_count(sym) >= MARA_DAILY_ENTRY_LIMIT:" in source
    assert "def mara_second_entry_eligible()" in source
