"""Ensure watch calibration candidates remain replay-only and summarized."""
import unittest
from pathlib import Path

class WatchCalibrationTests(unittest.TestCase):
    def test_candidate_configs_have_summary_rows_and_no_live_install(self):
        source=Path("backend/v18344_replay_lab.py").read_text()
        for key in ("intended_clear_60","intended_clear_90","intended_clear_120","intended_clear_180"):
            self.assertGreaterEqual(source.count('"'+key+'"'),2)
        self.assertIn('"liveTradingChanged":False',source)
        self.assertNotIn("market_sell_qty =",source)
    def test_shorter_candidates_are_explicit(self):
        source=Path("backend/v18344_replay_lab.py").read_text()
        self.assertIn('"watch":60,"extend":60,"clear":True',source)
        self.assertIn('"watch":90,"extend":60,"clear":True',source)
if __name__=="__main__": unittest.main()
