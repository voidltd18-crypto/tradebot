import unittest
import sqlite3
from backend.v19018_replay_health import replay_health_snapshot

class Tests(unittest.TestCase):
    def test_link_consistency(self):
        db=sqlite3.connect(":memory:")
        db.executescript("""
        CREATE TABLE trade_replay_sessions(id INTEGER,symbol TEXT,ended_at TEXT,closed_trade_id INTEGER);
        CREATE TABLE closed_trades(id INTEGER,symbol TEXT,timestamp TEXT);
        CREATE TABLE trade_replay_points(id INTEGER);
        INSERT INTO closed_trades VALUES (1,'ABC','2026-10-14T10:00:00Z');
        INSERT INTO closed_trades VALUES (2,'OTHER','2026-10-14T10:00:00Z');
        INSERT INTO closed_trades VALUES (3,'ABC','2026-10-14T15:00:00Z');
        INSERT INTO trade_replay_sessions VALUES (1,'ABC','2026-10-14T10:00:05Z',1);
        INSERT INTO trade_replay_sessions VALUES (2,'ABC','2026-10-14T10:00:05Z',2);
        INSERT INTO trade_replay_sessions VALUES (3,'ABC','2026-10-14T10:00:05Z',3);
        INSERT INTO trade_replay_sessions VALUES (4,'ABC','2026-10-14T10:00:05Z',999);
        INSERT INTO trade_replay_sessions VALUES (5,'ABC','2026-10-14T10:00:05Z',NULL);
        """)
        r=replay_health_snapshot(db)
        self.assertEqual(r["directLinkedSessions"],4)
        self.assertEqual(r["linkedWithin1hAndSameSymbol"],1)
        self.assertEqual(r["linkedMissingTrade"],1)
        self.assertEqual(r["linkedSymbolMismatch"],1)
        self.assertEqual(r["linkedOver1hApart"],1)
        db.close()
if __name__=="__main__":unittest.main()
