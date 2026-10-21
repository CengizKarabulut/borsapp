import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from scripts.atc_market_status import load_market_events, market_event_for


class OfficialMarketStatusTests(unittest.TestCase):
    def test_real_halt_is_dated_and_never_carried_into_reopening(self):
        rows = load_market_events()
        now = datetime.fromisoformat("2026-10-20T17:00:00+03:00")
        event = market_event_for("RALYH", date(2026, 10, 20), observed_at=now, events=rows)
        self.assertEqual(event["source_url"], "https://www.kap.org.tr/tr/Bildirim/1684170")
        self.assertIsNone(market_event_for("RALYH", date(2026, 10, 21), observed_at=now, events=rows))
        self.assertIsNone(market_event_for("AKBNK", date(2026, 10, 20), observed_at=now, events=rows))

    def test_unpublished_notice_is_not_used_as_historical_knowledge(self):
        rows = load_market_events()
        self.assertIsNone(market_event_for("RALYH", date(2026, 10, 20),
            observed_at=datetime.fromisoformat("2026-10-19T19:00:00+03:00"), events=rows))

    def test_untrusted_provenance_and_overlapping_notices_are_rejected(self):
        rows = load_market_events()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "events.json"
            for events in ([{**rows[0], "source_url": "https://kap.org.tr.evil.test/tr/Bildirim/1684170"}],
                           [{**rows[0], "source_url": "https://:test@www.kap.org.tr/tr/Bildirim/1684170"}],
                           [{**rows[0], "source_url": "https://www.kap.org.tr:443/tr/Bildirim/1684170"}],
                           [rows[0], rows[0]],
                           [{**rows[0], "resume_session": "2026-10-20"}]):
                path.write_text(json.dumps({"schema": "atc-official-market-events-v1", "events": events}))
                with self.assertRaises(ValueError):
                    load_market_events(path)
