import unittest
from backend.v19016_replay_bounds import bound_replay_to_exit

class ReplayBoundTests(unittest.TestCase):
    def test_excludes_post_exit_price(self):
        points=[
          {"point_time":"2026-10-14T12:00:00Z","price":100},
          {"point_time":"2026-10-14T12:00:10Z","price":101},
          {"point_time":"2026-10-14T12:00:20Z","price":200}]
        rows,status=bound_replay_to_exit(points,"2026-10-14T12:00:15Z")
        self.assertEqual(status,"BOUNDED_TO_EXIT")
        self.assertEqual([p["price"] for p in rows],[100,101])
    def test_rejects_missing_preexit_data(self):
        rows,status=bound_replay_to_exit([
          {"point_time":"2026-10-14T12:00:20Z","price":100}],
          "2026-10-14T12:00:15Z")
        self.assertEqual(rows,[])
        self.assertEqual(status,"INSUFFICIENT_PRE_EXIT_POINTS")
    def test_rejects_missing_exit_time(self):
        self.assertEqual(bound_replay_to_exit([],None)[1],"EXIT_TIMESTAMP_MISSING")
if __name__=="__main__":unittest.main()
