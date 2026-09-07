from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.providers import ProviderBar

ISTANBUL = ZoneInfo("Europe/Istanbul")


class BorsapyProviderTests(unittest.TestCase):
    def test_provider_timestamp_is_normalized_before_as_of_filtering(self) -> None:
        provider = BorsapyProvider()
        self.assertLessEqual(
            provider._opened_at(datetime(2026, 9, 7, 12, 0)),
            datetime(2026, 9, 7, 12, 15, tzinfo=ISTANBUL),
        )

    def test_bar_opened_at_as_of_is_partial(self) -> None:
        provider = BorsapyProvider()
        self.assertTrue(
            provider._last_is_partial(
                datetime(2026, 9, 7, 12, 15),
                Timeframe.M15,
                datetime(2026, 9, 7, 12, 15, tzinfo=ISTANBUL),
            )
        )

    def test_closed_bar_is_not_partial(self) -> None:
        provider = BorsapyProvider()
        bar = ProviderBar(datetime(2026, 9, 7, 12, 0), 10, 11, 9, 10.5, 100)
        self.assertFalse(
            provider._last_is_partial(
                bar.timestamp,
                Timeframe.M15,
                datetime(2026, 9, 7, 12, 15, tzinfo=ISTANBUL),
            )
        )


if __name__ == "__main__":
    unittest.main()
