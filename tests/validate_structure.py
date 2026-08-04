"""Dependency-free structural validation for CI and local checks."""
import ast
from pathlib import Path

root = Path(__file__).resolve().parents[1]
entry = root / "backend" / "main.py"
legacy = root / "backend" / "legacy" / "monolith.py"

for path in (entry, legacy):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

source = legacy.read_text(encoding="utf-8")
required = (
    '/v12/ceo/status',
    '/v12/ceo/journal',
    '/v12/ceo/reviews',
    '/v12/ceo/constitution',
    '/v12/board/status',
    '/v12/board/history',
    '/v12/board/constitution',
)
missing = [route for route in required if route not in source]
if missing:
    raise SystemExit(f"Missing routes: {missing}")
print("OK: syntax valid and all V12 CEO/Board routes are present")
