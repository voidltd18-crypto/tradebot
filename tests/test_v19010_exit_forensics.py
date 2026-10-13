import unittest
from backend.v19010_exit_forensics import summarize_exit_path

class ForensicsTests(unittest.TestCase):
    def test_peak_and_gap(self):
        points=[
          {"observed_at":"2026-10-13T14:00:00Z","price":100},
          {"observed_at":"2026-10-13T14:00:10Z","price":106},
          {"observed_at":"2026-10-13T14:01:10Z","price":101}]
        row=summarize_exit_path(points,100.1,100)
        self.assertEqual(row["coverage"],"SAMPLED_ONLY")
        self.assertEqual(row["largestSampleGapSec"],60)
        self.assertAlmostEqual(row["sampledGivebackPp"],5.9)
        self.assertTrue(row["notAnExecutableQuote"])

    def test_invalid_points_and_missing_coverage(self):
        row=summarize_exit_path([{"observed_at":"invalid","price":10}],9,10)
        self.assertEqual(row["coverage"],"INSUFFICIENT")
        row=summarize_exit_path([],9,10)
        self.assertEqual(row["samples"],0)

if __name__=="__main__": unittest.main()
