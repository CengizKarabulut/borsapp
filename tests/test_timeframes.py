from __future__ import annotations

import unittest

from market_intelligence.core.timeframes import Timeframe, parse_timeframe


class TimeframeTests(unittest.TestCase):
    def test_legacy_aliases_are_normalized(self) -> None:
        self.assertEqual(parse_timeframe("1H"), Timeframe.H1)
        self.assertEqual(parse_timeframe("60m"), Timeframe.H1)
        self.assertEqual(parse_timeframe("1D"), Timeframe.D1)
        self.assertEqual(parse_timeframe("1W"), Timeframe.W1)
        self.assertEqual(parse_timeframe("1M"), Timeframe.MO1)

    def test_intraday_minutes(self) -> None:
        self.assertEqual(Timeframe.M45.minutes, 45)
        self.assertTrue(Timeframe.H4.is_intraday)
        self.assertFalse(Timeframe.D1.is_intraday)

    def test_unknown_timeframe_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            parse_timeframe("7h")


if __name__ == "__main__":
    unittest.main()
