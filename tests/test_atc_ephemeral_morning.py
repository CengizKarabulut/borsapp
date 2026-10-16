from __future__ import annotations

import unittest
from datetime import date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from scripts.atc_ephemeral_morning import read_last_close
from scripts.atc_telegram_briefings import morning_messages

IST = ZoneInfo("Europe/Istanbul")


class MockProvider:
    def __init__(self, bars):
        self.bars = bars

    def fetch(self, request):
        return SimpleNamespace(bars=self.bars)


class MorningEphemeralTests(unittest.TestCase):
    def test_previous_session_real_candle_only(self):
        expected = date(2026, 10, 15)
        one = SimpleNamespace(
            timestamp=datetime(2026, 10, 15, 10, tzinfo=IST),
            high=116.0, low=100.0, close=112.0, volume=1300,
        )
        current = SimpleNamespace(
            timestamp=datetime(2026, 10, 16, 10, tzinfo=IST),
            high=200.0, low=95.0, close=196.0, volume=1200,
        )
        symbol, levels, turnover, state = read_last_close(
            "ASELS", day=expected,
            now=datetime(2026, 10, 16, 8, 35, tzinfo=IST),
            provider=MockProvider((one, current)),
        )
        self.assertEqual(symbol, "ASELS")
        self.assertEqual(state, "TEYITLI")
        self.assertAlmostEqual(turnover, 112.0 * 1300.0)
        self.assertEqual(len(levels), 5)
        self.assertAlmostEqual(levels[2], (116 + 100 + 112) / 3)

    def test_missing_candle_is_not_substituted_from_today(self):
        today = SimpleNamespace(
            timestamp=datetime(2026, 10, 16, 10, tzinfo=IST),
            high=116.0, low=100.0, close=112.0, volume=1300,
        )
        entry = read_last_close(
            "ASELS", day=date(2026, 10, 15),
            now=datetime(2026, 10, 16, 11, tzinfo=IST),
            provider=MockProvider((today,)),
        )
        self.assertEqual(entry[3], "VERI_YOK")

    def test_genuine_fallback_returns_only_one_provider_close_and_source(self):
        previous = SimpleNamespace(
            timestamp=datetime(2026, 10, 15, 10, tzinfo=IST),
            high=116.0, low=100.0, close=112.0, volume=1300,
        )
        today = SimpleNamespace(
            timestamp=datetime(2026, 10, 16, 10, tzinfo=IST),
            high=200.0, low=90.0, close=199.0, volume=50,
        )
        first = MockProvider((today,))
        second = MockProvider((previous, today))
        second.name = "second_actual_vendor"
        second.fetch = lambda request: SimpleNamespace(
            bars=second.bars, price_basis="raw",
        )
        row = read_last_close(
            "ASELS", day=date(2026, 10, 15),
            now=datetime(2026, 10, 16, 15, tzinfo=IST),
            provider=(first, second), include_source=True,
        )
        self.assertEqual(row[3], "TEYITLI")
        self.assertEqual(row[4], "second_actual_vendor/raw")
        self.assertAlmostEqual(row[1][2], (116 + 100 + 112) / 3)
        message, data = morning_messages(date(2026, 10, 15), [row] * 630)
        self.assertIn("KaynakFiyatBazi", data.decode("utf-8-sig"))
        self.assertIn("düzeltme bazları", message)

    def test_morning_fails_closed_below_ninety_percent(self):
        rows = [("TEST", None, None, "VERI_YOK") for _ in range(630)]
        with self.assertRaisesRegex(ValueError, "coverage insufficient"):
            morning_messages(date(2026, 10, 15), rows)


if __name__ == "__main__":
    unittest.main()
