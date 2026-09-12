import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.adapters.yfinance import YFinanceBistProvider
from market_intelligence.market_data.providers import FetchRequest

TZ = ZoneInfo("Europe/Istanbul")


class ProviderSessionAlignmentTests(unittest.TestCase):
    def test_valid_period_covers_requested_hourly_history(self):
        provider = BorsapyProvider()
        now = datetime(2026, 9, 11, 18, tzinfo=TZ)
        self.assertEqual(
            provider._history_period(FetchRequest("ASELS", Timeframe.H1, 420, now)), "3mo"
        )
        self.assertEqual(
            provider._history_period(FetchRequest("ASELS", Timeframe.H1, 1680, now)), "1y"
        )

    def test_filter_before_tail_preserves_complete_regular_bars(self):
        provider = BorsapyProvider()
        stamps = pd.DatetimeIndex(
            [datetime(2026, 9, 11, h, tzinfo=TZ) for h in [9, 15, 16, 17, 18]]
        )
        data = pd.DataFrame(
            {name: [1.0] * 5 for name in ["Open", "High", "Low", "Close", "Volume"]}, index=stamps
        )
        result = provider._completed_regular_bars(
            data, FetchRequest("ASELS", Timeframe.H1, 2, datetime(2026, 9, 11, 18, tzinfo=TZ))
        )
        self.assertEqual([bar.timestamp.hour for bar in result], [16, 17])

    def test_yahoo_hourly_uses_real_half_hour_buckets(self):
        stamps = pd.DatetimeIndex(
            [
                datetime(2026, 9, 11, 9, 30, tzinfo=TZ),
                datetime(2026, 9, 11, 10, tzinfo=TZ),
                datetime(2026, 9, 11, 10, 30, tzinfo=TZ),
                datetime(2026, 9, 11, 11, tzinfo=TZ),
            ]
        )
        data = pd.DataFrame(
            {
                "Open": [99, 10, 11, 90],
                "High": [99, 12, 14, 90],
                "Low": [99, 9, 10, 90],
                "Close": [99, 11, 13, 90],
                "Volume": [99, 100, 200, 90],
            },
            index=stamps,
        )
        ticker = Mock()
        ticker.history.return_value = data
        with patch.dict(
            sys.modules, {"yfinance": SimpleNamespace(Ticker=Mock(return_value=ticker))}
        ):
            result = YFinanceBistProvider().fetch(
                FetchRequest("ASELS", Timeframe.H1, 10, datetime(2026, 9, 11, 11, tzinfo=TZ))
            )
        self.assertEqual(ticker.history.call_args.kwargs["interval"], "30m")
        self.assertEqual(len(result.bars), 1)
        bar = result.bars[0]
        self.assertEqual(
            (
                bar.timestamp.hour,
                bar.timestamp.minute,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume,
            ),
            (10, 0, 10, 14, 9, 13, 300),
        )
        self.assertFalse(result.last_bar_is_partial)

    def test_shifted_hourly_native_bar_is_not_relabelled(self):
        stamps = pd.DatetimeIndex([datetime(2026, 9, 11, 10, 30, tzinfo=TZ)])
        data = pd.DataFrame(
            {name: [1.0] for name in ["Open", "High", "Low", "Close", "Volume"]}, index=stamps
        )
        self.assertEqual(
            BorsapyProvider()._completed_regular_bars(
                data, FetchRequest("ASELS", Timeframe.H1, 10, datetime(2026, 9, 11, 18, tzinfo=TZ))
            ),
            [],
        )
