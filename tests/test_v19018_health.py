import sqlite3
import unittest
from backend.v19018_replay_health import replay_health_snapshot

class HealthSummaryTests(unittest.TestCase):
    def test_counts_without_identifiers(self):
        c=sqlite3.connect(":memory:")
        c.execute("CREATE TABLE trade_replay_sessions(id INTEGER,ended_at TEXT,closed_trade_id INTEGER)")
        c.execute("CREATE TABLE trade_replay_points(id INTEGER)")
        c.execute("CREATE TABLE closed_trades(id INTEGER)")
        c.execute("INSERT INTO trade_replay_sessions VALUES(1,NULL,NULL)")
        c.execute("INSERT INTO trade_replay_sessions VALUES(2,'2026-10-14',NULL)")
        c.execute("INSERT INTO trade_replay_sessions VALUES(3,'2026-10-14',55)")
        c.execute("INSERT INTO trade_replay_points VALUES(1)")
        c.execute("INSERT INTO closed_trades VALUES(55)")
        s=replay_health_snapshot(c)
        self.assertEqual(s["sessionCount"],3)
        self.assertEqual(s["closedSessions"],2)
        self.assertEqual(s["directLinkedSessions"],1)
        self.assertEqual(s["pointCount"],1)
        self.assertEqual(s["closedTrades"],1)
        self.assertTrue(s["readOnly"])
        c.close()
    def test_missing_tables_are_reported_unknown(self):
        c=sqlite3.connect(":memory:")
        s=replay_health_snapshot(c)
        self.assertIsNone(s["sessionCount"])
        c.close()
if __name__=="__main__":unittest.main()
