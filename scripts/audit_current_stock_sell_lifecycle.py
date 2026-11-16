"""Read-only analysis of CURRENT deployed TradeBot stock sell lifecycle.

Parses monolith without importing it. No credentials, brokerage access,
database writes, application startup or trading. Findings are observations
of the *exact Git checkout*, not proof of broker live execution.
"""
import ast
import json
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend/legacy/monolith.py"
NAME_KEYS = (
    "market_sell_qty",
    "register_pending_sell_order",
    "reconcile_pending_sell_orders",
    "has_open_order",
)
CALL_KEYS = (
    "submit_order",
    "register_pending_sell_order",
    "lock_symbol_until_tomorrow",
    "reset_position_peak",
    "get_orders",
    "get_order_by_id",
)

def walk():
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    tree = ast.parse("\n".join(lines))
    matches = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name not in NAME_KEYS:
            continue
        calls = sorted(
            [{"name": (ast.unparse(c.func) if isinstance(c.func, (ast.Attribute, ast.Name)) else "dynamic"),
              "line": c.lineno}
             for c in ast.walk(node) if isinstance(c, ast.Call)
             and any(key in ast.unparse(c.func) for key in CALL_KEYS)],
            key=lambda e: e["line"],
        )
        matches.append({
            "name": node.name, "start": node.lineno, "end": node.end_lineno,
            "calls": calls,
            "source": "\n".join(
                f"{i}: {lines[i-1]}" for i in range(node.lineno, min(node.end_lineno,node.lineno+130)+1)
            ),
        })
    return {"source":str(SOURCE.relative_to(SOURCE.parents[1])),
            "sourceLineCount":len(lines),
            "functions":matches,
            "warnings": [
                "Static call ordering is NOT proof of production execution order.",
                "Never infer broker fill from order acceptance.",
                "Treat unknown submission outcomes as potentially accepted.",
            ]}

if __name__ == "__main__":
    print(json.dumps(walk(), indent=2))
