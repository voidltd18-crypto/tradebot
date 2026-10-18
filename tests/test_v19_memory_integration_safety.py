"""V19 opt-in telemetry safety gates; never import the live trading application."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "backend" / "legacy" / "monolith.py"


class MemoryIntegrationSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        cls.snapshot = next(
            node for node in cls.tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "_v19_memory_snapshot"
        )

    def test_telemetry_flag_defaults_disabled(self):
        flag_reads = [
            node for node in ast.walk(self.snapshot)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "getenv"
            and len(node.args) >= 2
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "V19_COLLECTION_TELEMETRY_ENABLED"
        ]
        self.assertEqual(len(flag_reads), 1)
        self.assertEqual(flag_reads[0].args[1].value, "false")

    def test_sampler_is_only_called_inside_opt_in_branch(self):
        branches = [
            node for node in ast.walk(self.snapshot)
            if isinstance(node, ast.If)
            and "V19_COLLECTION_TELEMETRY_ENABLED" in ast.unparse(node.test)
        ]
        self.assertEqual(len(branches), 1)
        calls = [
            node for stmt in branches[0].body for node in ast.walk(stmt)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sample_collections"
        ]
        self.assertEqual(len(calls), 1)

    def test_no_order_calls_inside_memory_snapshot(self):
        forbidden = {"submit_order", "close_position", "close_all_positions", "buy", "sell"}
        for node in ast.walk(self.snapshot):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
                self.assertNotIn(name, forbidden)


if __name__ == "__main__":
    unittest.main()
