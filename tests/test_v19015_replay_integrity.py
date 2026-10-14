import unittest
from backend.v19015_replay_integrity import evidence_quality, quality_summary

class ReplayIntegrityTests(unittest.TestCase):
    def test_clean_direct_replay(self):
        t={"id":1,"symbol":"XYZ","timestamp":"2026-10-13T14:00:30Z","reason":"PROFIT"}
        p=[{"point_time":"2026-10-13T14:00:00Z","price":100},
           {"point_time":"2026-10-13T14:00:20Z","price":101}]
        r=evidence_quality(t,{},p,"direct","recorded")
        self.assertEqual(r["flags"],[])
        self.assertEqual(quality_summary([r])["cleanEvidenceCount"],1)

    def test_flags_mismatches_and_unrecorded_fx(self):
        t={"id":2,"symbol":"XYZ","timestamp":"2026-10-13T14:10:00Z","reason":""}
        p=[{"point_time":"2026-10-13T14:00:00Z","price":100},
           {"point_time":"2026-10-13T14:00:20Z","price":101}]
        r=evidence_quality(t,{},p,"reconciled","estimated")
        for flag in ("REPLAY_LINK_NOT_DIRECT","LAST_SAMPLE_OVER_60S_BEFORE_EXIT",
                     "FX_RATE_NOT_RECORDED","MISSING_EXIT_REASON"):
            self.assertIn(flag,r["flags"])
    def test_future_points_flagged(self):
        t={"timestamp":"2026-10-13T14:00:00Z","reason":"TEST"}
        p=[{"point_time":"2026-10-13T14:01:00Z","price":1},
           {"point_time":"2026-10-13T14:01:20Z","price":1}]
        self.assertIn("REPLAY_CONTINUES_OVER_30S_AFTER_EXIT",
                      evidence_quality(t,{},p,"direct","recorded")["flags"])

if __name__=="__main__":unittest.main()
