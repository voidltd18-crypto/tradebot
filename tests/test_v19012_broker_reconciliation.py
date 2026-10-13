import unittest
from backend.v19012_broker_reconciliation import reconcile

class ReconTests(unittest.TestCase):
    def test_single_candidate_not_proof(self):
        e=[{"atUtc":"2026-10-13T14:00:04Z","symbol":"ABC","outcome":"returned"}]
        o=[{"symbol":"ABC","side":"sell","id":"123","created_at":"2026-10-13T14:00:00Z",
            "filled_at":"2026-10-13T14:00:15Z","status":"filled","filled_avg_price":"10.12","filled_qty":"2"}]
        r=reconcile(e,o)[0]
        self.assertEqual(r["matchStatus"],"ONE_TIME_CANDIDATE_NOT_PROOF")
        self.assertEqual(r["brokerOrderCandidates"][0]["secondsFromOrderCreatedToFilled"],15)
    def test_ambiguous_and_no_candidate(self):
        e=[{"atUtc":"2026-10-13T14:00:04Z","symbol":"ABC"}]
        o=[{"symbol":"ABC","side":"sell","id":"1","created_at":"2026-10-13T14:00:00Z"},
           {"symbol":"ABC","side":"sell","id":"2","created_at":"2026-10-13T14:00:02Z"}]
        self.assertEqual(reconcile(e,o)[0]["matchStatus"],"AMBIGUOUS")
        self.assertEqual(reconcile(e,[])[0]["matchStatus"],"NO_CANDIDATE")
    def test_no_buy_match(self):
        e=[{"atUtc":"2026-10-13T14:00:00Z","symbol":"ABC"}]
        o=[{"symbol":"ABC","side":"buy","created_at":"2026-10-13T14:00:00Z"}]
        self.assertEqual(reconcile(e,o)[0]["candidateCount"],0)
if __name__=="__main__":unittest.main()
