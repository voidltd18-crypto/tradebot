"""Static guardrails for opt-in V19 runtime telemetry; no trading imports."""
import ast
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "backend" / "legacy" / "monolith.py"


class OptInTelemetrySafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        cls.fn = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_v19_optional_memory_snapshot")
        cls.cleanup = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                           and node.name == "_release_transient_memory")

    def test_disabled_by_default(self):
        getenv_calls = [node for node in ast.walk(self.fn) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr == "getenv"
                        and len(node.args) >= 2
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "V19_COLLECTION_TELEMETRY_ENABLED"]
        self.assertEqual(len(getenv_calls), 1)
        self.assertEqual(getenv_calls[0].args[1].value, "false")

    def test_flag_guard_precedes_sampler(self):
        first = self.fn.body[1] if isinstance(self.fn.body[0], ast.Expr) else self.fn.body[0]
        self.assertIsInstance(first, ast.If)
        self.assertIn("V19_COLLECTION_TELEMETRY_ENABLED", ast.unparse(first.test))
        self.assertTrue(any(isinstance(node, ast.Return) for node in first.body))
        self.assertTrue(any(isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Name)
                            and node.func.id == "sample_collections"
                            for node in ast.walk(self.fn)))

    def test_no_order_or_persistence_calls(self):
        forbidden = {"submit_order", "close_position", "close_all_positions",
                     "buy", "sell", "commit", "execute", "executemany"}
        for node in ast.walk(self.fn):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else "")
                self.assertNotIn(name, forbidden)

    def test_cleanup_hook_is_present(self):
        calls = [node for node in ast.walk(self.cleanup) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "_v19_optional_memory_snapshot"]
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
