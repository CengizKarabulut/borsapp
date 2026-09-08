from __future__ import annotations

import unittest

from market_intelligence.shadow.bridge import to_legacy_frame
from tests.test_volume_spike import frame


class ShadowBridgeTests(unittest.TestCase):
    def test_canonical_frame_has_legacy_columns_local_timezone_and_order(self) -> None:
        legacy = to_legacy_frame(frame())
        self.assertEqual(list(legacy.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertEqual(str(legacy.index.tz), "Europe/Istanbul")
        self.assertTrue(legacy.index.is_monotonic_increasing)
        self.assertEqual(legacy.index[0].to_pydatetime(), frame().bars[0].open_time)
        self.assertEqual(float(legacy.iloc[-1]["Close"]), 10.0)
