import json
import unittest
from datetime import UTC, datetime

from market_intelligence.application.candidate_followups import enqueue_candidate_followups


class Connection:
    def __init__(self):
        self.keys = set()
        self.calls = []

    def execute(self, sql, args):
        self.calls.append(args)
        key = args[3]
        self.row = None if key in self.keys else ("id",)
        self.keys.add(key)
        return self

    def fetchone(self):
        return self.row


class CandidateTests(unittest.TestCase):
    def test_short_timeframes_do_not_enqueue_other_topics(self):
        db = Connection()
        for tf in ("15m", "30m", "45m", "2h"):
            self.assertEqual(enqueue_candidate_followups(db, tf, datetime.now(UTC), [{}], 1), 0)
        self.assertEqual(db.calls, [])

    def test_limit_and_repeated_bar_and_daily_report_deduplication(self):
        db = Connection()
        ranked = [dict(symbol=f"S{i}", scanners=["a", "b"], direction="bullish") for i in range(25)]
        target = datetime(2026, 9, 11, 15, tzinfo=UTC)
        self.assertEqual(enqueue_candidate_followups(db, "1h", target, ranked, 1), 60)
        self.assertEqual(enqueue_candidate_followups(db, "1h", target, ranked, 1), 0)
        self.assertEqual(enqueue_candidate_followups(db, "4h", target, ranked, 1), 40)
        self.assertEqual(json.loads(db.calls[-1][4])["trigger_timeframe"], "4h")
        self.assertEqual(enqueue_candidate_followups(db, "1d", target, ranked, 1), 40)
        self.assertEqual(enqueue_candidate_followups(db, "1wk", target, ranked, 1), 40)
