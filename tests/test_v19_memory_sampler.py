"""Read-only V19 telemetry unit tests. Run: python -m unittest tests/test_v19_memory_sampler.py"""
import unittest
from backend.v19_memory_sampler import sample_collections, compare_samples


class MemorySamplerTests(unittest.TestCase):
    def test_samples_without_mutating_collections(self):
        rows = [{"symbol": "MARA"}]
        memory = {"MARA": {"trades": 1}}
        before_rows = rows.copy()
        before_memory = memory.copy()
        sample = sample_collections({"rows": rows, "memory": memory})
        self.assertEqual(sample["collection_lengths"], {"rows": 1, "memory": 1})
        self.assertEqual(rows, before_rows)
        self.assertEqual(memory, before_memory)
        self.assertIn("rss_mb", sample)

    def test_reports_growth(self):
        before = {"rss_mb": 100.0, "collection_lengths": {"rows": 5, "memory": 2}}
        after = {"rss_mb": 102.5, "collection_lengths": {"rows": 8, "memory": 2}}
        self.assertEqual(compare_samples(before, after), {
            "rss_delta_mb": 2.5, "collection_deltas": {"rows": 3, "memory": 0}
        })

    def test_missing_rss_is_supported(self):
        before = {"rss_mb": None, "collection_lengths": {"rows": 1}}
        after = {"rss_mb": None, "collection_lengths": {"rows": 1}}
        self.assertIsNone(compare_samples(before, after)["rss_delta_mb"])


if __name__ == "__main__":
    unittest.main()
