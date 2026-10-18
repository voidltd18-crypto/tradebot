"""V19 repeated-cycle memory sampler tests, without importing the trading bot.

Run: python -m unittest discover -s tests -p 'test_v19_memory_*.py'
"""
import gc
import unittest
from backend.v19_memory_sampler import sample_collections, compare_samples


class RepeatedCycleMemoryTests(unittest.TestCase):
    def test_reused_cache_does_not_grow_in_entry_count(self):
        candidate_rows = [{"symbol": f"TEST{i}", "score": i / 100} for i in range(100)]
        cache = {"rows": [], "symbols": []}
        retained_evidence = [{"cycle": 0, "symbol": "MARA"}]
        baseline = sample_collections({"rows": cache["rows"], "symbols": cache["symbols"], "evidence": retained_evidence})
        for _ in range(100):
            # Simulate a complete cache replacement, not live scanning.
            cache["rows"] = list(candidate_rows)
            cache["symbols"] = [row["symbol"] for row in candidate_rows]
            sample = sample_collections({"rows": cache["rows"], "symbols": cache["symbols"], "evidence": retained_evidence})
            self.assertEqual(sample["collection_lengths"], {"rows": 100, "symbols": 100, "evidence": 1})
        gc.collect()
        final = sample_collections({"rows": cache["rows"], "symbols": cache["symbols"], "evidence": retained_evidence})
        delta = compare_samples(baseline, final)
        self.assertEqual(delta["collection_deltas"], {"rows": 100, "symbols": 100, "evidence": 0})

    def test_accumulating_history_is_detected_not_deleted(self):
        history = []
        start = sample_collections({"history": history})
        for cycle in range(50):
            history.append({"cycle": cycle})
        end = sample_collections({"history": history})
        self.assertEqual(compare_samples(start, end)["collection_deltas"]["history"], 50)
        self.assertEqual(len(history), 50)


if __name__ == "__main__":
    unittest.main()
