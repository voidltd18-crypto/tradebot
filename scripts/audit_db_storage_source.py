"""Read-only bounded audit for SQLite storage and slow DB writer paths."""
import ast
import json
import re
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"
lines = p.read_text(encoding="utf-8").splitlines()
tree = ast.parse("\n".join(lines))
pattern = re.compile(r"SQLITE_DB_FILE|db_connect|DB_WRITER|_v13_upsert_knowledge|flush_pending|sqlite3.connect|/var/data|busy_timeout|journal_mode|_persistent_position_peak", re.I)
out = {"readOnly": True, "sourceLines": len(lines), "matches": [], "functions": []}
for n, line in enumerate(lines, 1):
    if pattern.search(line) and not line.strip().startswith("#"):
        out["matches"].append({"line": n, "source": line[:200].rstrip()})
        if len(out["matches"]) >= 125:
            break
for node in tree.body:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if re.search(r"db_connect|db.writer|upsert_knowledge|flush_pending|db_init|init_db", node.name, re.I):
            snippets = []
            for k in range(node.lineno, min(node.end_lineno, node.lineno+95)+1):
                snippets.append({"line": k, "source": lines[k-1][:210]})
            out["functions"].append({"name": node.name, "start": node.lineno, "end": node.end_lineno, "snippet": snippets})
            if len(out["functions"]) >= 15:
                break
print(json.dumps(out, indent=2))
