from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.canonicalizer import Canonicalizer
from market_intelligence.market_data.providers import ProviderBar, ProviderFrame, TimestampKind


def provider_frame(
    *,
    count: int = 32,
    last_partial: bool = False,
) -> ProviderFrame:
    start = datetime(2026, 9, 7, 10, 0)
    bars = tuple(
        ProviderBar(
            timestamp=start + timedelta(minutes=15 * index),
            open=10.0 + index / 100,
            high=10.5 + index / 100,
            low=9.5 + index / 100,
            close=10.1 + index / 100,
            volume=100.0 + index,
        )
        for index in range(count)
    )
    return ProviderFrame(
        provider="fixture",
        provider_symbol="TEST",
        timeframe=Timeframe.M15,
        timestamp_kind=TimestampKind.OPEN,
        timestamp_timezone="Europe/Istanbul",
        price_basis=PriceBasis.SPLIT_ADJUSTED,
        bars=bars,
        last_bar_is_partial=last_partial,
    )


def canonical(source: ProviderFrame, target: Timeframe = Timeframe.M45):
    return Canonicalizer().build(
        instrument_id="instrument-1",
        symbol_at_snapshot="TEST",
        market="BIST",
        provider_frame=source,
        target_timeframe=target,
        series_revision=1,
    )


class CanonicalizerTests(unittest.TestCase):
    def test_45m_uses_session_anchor_and_drops_30m_tail(self) -> None:
        result = canonical(provider_frame())
        self.assertEqual(len(result.bars), 10)
        self.assertEqual(result.bars[0].open_time.hour, 10)
        self.assertEqual(result.bars[0].close_time.minute, 45)
        self.assertEqual(result.bars[-1].close_time.hour, 17)
        self.assertEqual(result.bars[-1].close_time.minute, 30)

    def test_snapshot_hash_is_content_addressed(self) -> None:
        first = canonical(provider_frame())
        second = canonical(provider_frame())
        self.assertEqual(first.snapshot_id, second.snapshot_id)

        changed_bars = list(provider_frame().bars)
        changed_bars[0] = ProviderBar(
            timestamp=changed_bars[0].timestamp,
            open=changed_bars[0].open,
            high=changed_bars[0].high,
            low=changed_bars[0].low,
            close=changed_bars[0].close,
            volume=999.0,
        )
        changed = canonical(
            ProviderFrame(
                provider="fixture",
                provider_symbol="TEST",
                timeframe=Timeframe.M15,
                timestamp_kind=TimestampKind.OPEN,
                timestamp_timezone="Europe/Istanbul",
                price_basis=PriceBasis.SPLIT_ADJUSTED,
                bars=tuple(changed_bars),
            )
        )
        self.assertNotEqual(first.snapshot_id, changed.snapshot_id)

    def test_provider_partial_bar_is_removed_before_direct_use(self) -> None:
        result = canonical(provider_frame(count=8, last_partial=True), Timeframe.M15)
        self.assertEqual(len(result.bars), 7)

    def test_aware_utc_timestamp_is_converted_to_market_timezone(self) -> None:
        source = ProviderFrame(
            provider="fixture",
            provider_symbol="TEST",
            timeframe=Timeframe.H1,
            timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone="UTC",
            price_basis=PriceBasis.RAW,
            bars=(
                ProviderBar(
                    timestamp=datetime(2026, 9, 7, 7, 0, tzinfo=UTC),
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=100,
                ),
            ),
        )
        result = canonical(source, Timeframe.H1)
        self.assertEqual(result.bars[0].open_time.hour, 10)
        self.assertEqual(result.bars[0].open_time.utcoffset(), timedelta(hours=3))


if __name__ == "__main__":
    unittest.main()
