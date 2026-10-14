import unittest
from backend.v19017_stop_replay_validation import stop_discrepancy, summary

class StopValidationTests(unittest.TestCase):
    def test_first_sampled_stop_before_realised_exit(self):
        t={"id":1,"symbol":"TEST","entry_price":100,"exit_price":98,"qty":2,"timestamp":"2026-10-14T14:00:30Z"}
        pts=[{"point_time":"2026-10-14T14:00:00Z","price":100},
             {"point_time":"2026-10-14T14:00:10Z","price":98.4},
             {"point_time":"2026-10-14T14:01:00Z","price":50}]
        r=stop_discrepancy(t,pts,"reconciled")
        self.assertEqual(r["firstStopMarkPrice"],98.4)
        self.assertEqual(r["samplesBeforeExit"],2)
        self.assertIn("UNVERIFIED_REPLAY_LINK",r["issues"])
        self.assertFalse(r["eligibleForCalibration"])
        self.assertEqual(summary([r])["usableForAutomaticPromotion"],0)
    def test_no_trigger(self):
        t={"id":2,"symbol":"TEST","entry_price":100,"exit_price":101,"qty":1,"timestamp":"2026-10-14T14:00:30Z"}
        pts=[{"point_time":"2026-10-14T14:00:00Z","price":100},
             {"point_time":"2026-10-14T14:00:10Z","price":100.2}]
        r=stop_discrepancy(t,pts,"direct")
        self.assertIsNone(r["firstStopMarkPrice"])
        self.assertIn("NO_SAMPLED_STOP_TRIGGER",r["issues"])
if __name__=="__main__": unittest.main()
