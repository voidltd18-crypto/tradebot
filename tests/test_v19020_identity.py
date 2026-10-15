import unittest
from backend.v19020_replay_identity import direct_match,unique_direct_sessions

T={"id":5,"symbol":"ABC","timestamp":"2026-10-15T09:00:00Z"}
S={"id":9,"closed_trade_id":5,"symbol":"ABC","ended_at":"2026-10-15T09:00:10Z"}
class IdentityTests(unittest.TestCase):
    def test_valid_consistent_direct(self):
        self.assertTrue(direct_match(T,S))
        self.assertEqual(unique_direct_sessions([T],[S])[5]["id"],9)
    def test_symbol_and_time_rejection(self):
        self.assertFalse(direct_match(T,{**S,"symbol":"XYZ"}))
        self.assertFalse(direct_match(T,{**S,"ended_at":"2026-10-14T09:00:00Z"}))
    def test_duplicate_direct_is_ambiguous(self):
        self.assertEqual(unique_direct_sessions([T],[S,{**S,"id":10}]),{})
    def test_orphan_id_not_direct(self):
        self.assertEqual(unique_direct_sessions([T],[{**S,"closed_trade_id":999}]),{})
if __name__=="__main__":unittest.main()
