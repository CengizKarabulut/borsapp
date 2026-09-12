from __future__ import annotations

import os
import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.application.live_scans import SUMMARY_SQL


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "TEST_DATABASE_URL is not set")
class ScanSummarySQLTests(unittest.TestCase):
    def test_latest_revision_deduplicates_and_excludes_other_bars_and_universes(self):
        import psycopg
        with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as connection:
            with connection.transaction(force_rollback=True):
                connection.execute("CREATE TEMP TABLE scan_cycles (cycle_id int, universe_id text)")
                connection.execute("CREATE TEMP TABLE scan_evaluations (evaluation_id int, cycle_id int, instrument_id int, scanner_id text, symbol_at_evaluation text, status text, timeframe text, bar_time timestamptz, evaluated_at timestamptz, ruleset_hash text default 'current')")
                connection.execute("INSERT INTO scan_cycles VALUES (1,'BIST_ALL'),(2,'OTHER')")
                now = datetime(2026, 9, 11, 12, tzinfo=UTC)
                rows = [
                    (1,1,1,'signal.test','ONE','match','15m',now,now),
                    (2,1,1,'signal.test','ONE','no_match','15m',now,now+timedelta(seconds=1)),
                    (3,1,2,'signal.test','TWO','match','15m',now,now),
                    (4,1,3,'signal.test','THREE','unknown','15m',now,now),
                    (5,1,4,'signal.test','OLD','match','15m',now-timedelta(minutes=15),now),
                    (6,2,5,'signal.test','OTHER','match','15m',now,now),
                ]
                with connection.cursor() as cursor:
                    cursor.executemany('INSERT INTO scan_evaluations (evaluation_id,cycle_id,instrument_id,scanner_id,symbol_at_evaluation,status,timeframe,bar_time,evaluated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', rows)
                    cursor.execute(SUMMARY_SQL, ('BIST_ALL','15m',now,['current']))
                    self.assertEqual(cursor.fetchall(), [('signal.test',3,1,1,['TWO'])])
