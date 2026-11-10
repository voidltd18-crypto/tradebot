"""Read-only AST audit of the deployed-source legacy stock exit path.

This inspects source text, not runtime settings, account state or broker fills.
It emits bounded, narrowly filtered excerpts for manual review. It DOES NOT
claim a keyword occurrence proves a safety guard is executed.
"""
import ast
import json
import re
from pathlib import Path

MONOLITH = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"
TARGETS = ("manage_money_mode_positions", "get_all_positions",
           "_v17_runner_trail_decision", "market_sell_qty")
TERMS = re.compile(r"TRAIL|GIVEBACK|PEAK|HIGHEST|PROFIT|RUNNER|GRACE|SELL|PDT|LOCK|STOP|PARTIAL|ORDER|HOLD|COOLDOWN", re.I)


def audit(source_path=MONOLITH):
    source_path = Path(source_path)
    lines = source_path.read_text(encoding="utf-8").splitlines()
    tree = ast.parse("\n".join(lines), filename=source_path.name)
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    results = {}
    for name in TARGETS:
        node = functions.get(name)
        if node is None:
            results[name] = {"found": False, "excerpts": []}
            continue
        matches = []
        for line_number in range(node.lineno, node.end_lineno + 1):
            line = lines[line_number - 1].strip()
            if TERMS.search(line) and not line.startswith("#"):
                matches.append({"line": line_number, "code": line[:180]})
        results[name] = {
            "found": True,
            "startLine": node.lineno,
            "endLine": node.end_lineno,
            "matchedSourceLines": len(matches),
            "excerpts": matches[:110],
            "submissionBlock": [
                {"line": n, "code": lines[n - 1][:220]}
                for n in range(node.lineno, node.end_lineno + 1)
            ] if name == "market_sell_qty" else [],
            "runnerBlock": [
                {"line": n, "code": lines[n - 1][:200]}
                for n in range(node.lineno, node.end_lineno + 1)
            ] if name == "_v17_runner_trail_decision" else [],
            "trailingBlock": [
                {"line": n, "code": lines[n - 1][:200]}
                for n in range(max(node.lineno, 5010), min(node.end_lineno, 5057) + 1)
            ] if name == "manage_money_mode_positions" else [],
            "truncated": len(matches) > 110,
        }
    return {
        "readOnly": True,
        "verifiedRunningSettings": False,
        "verifiedLiveBrokerOrders": False,
        "file": str(source_path.name),
        "sourceLines": len(lines),
        "functions": results,
        "note": "Source scanning only; branch version may not equal running Render deployment",
    }


def main():
    print(json.dumps(audit(), indent=2))


if __name__ == "__main__":
    main()
