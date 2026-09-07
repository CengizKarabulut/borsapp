from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.application.ingestion import IngestionRequest, IngestionService
from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.market_data.providers import (
    FetchRequest,
    ProviderBar,
    ProviderFrame,
    TimestampKind,
)

ISTANBUL = ZoneInfo("Europe/Istanbul")


class FakeProvider:
    name = "fixture"

    def __init__(self, *, future_bar: bool = False) -> None:
        self.request: FetchRequest | None = None
        self.future_bar = future_bar

    def fetch(self, request: FetchRequest) -> ProviderFrame:
        self.request = request
        start = datetime(2026, 9, 7, 10, 0)
        count = 32
        bars = [
            ProviderBar(
                timestamp=start + timedelta(minutes=15 * index),
                open=10 + index / 100,
                high=11 + index / 100,
                low=9 + index / 100,
                close=10.5 + index / 100,
                volume=100 + index,
            )
            for index in range(count)
        ]
        if self.future_bar:
            bars.append(
                ProviderBar(
                    timestamp=datetime(2026, 9, 8, 10, 0),
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=100,
                )
            )
        return ProviderFrame(
            provider=self.name,
            provider_symbol=request.provider_symbol,
            timeframe=request.timeframe,
            timestamp_kind=TimestampKind.OPEN,
            timestamp_timezone="Europe/Istanbul",
            price_basis=PriceBasis.SPLIT_ADJUSTED,
            bars=tuple(bars),
        )


class FakeStore:
    def __init__(self) -> None:
        self.saved: list[CanonicalFrame] = []

    def save(self, frame: CanonicalFrame) -> None:
        self.saved.append(frame)


def request(timeframe: Timeframe = Timeframe.M45) -> IngestionRequest:
    return IngestionRequest(
        instrument_id="instrument-1",
        symbol="TEST",
        provider_symbol="TEST",
        market="BIST",
        timeframe=timeframe,
        bars=10,
        as_of=datetime(2026, 9, 7, 18, 15, tzinfo=ISTANBUL),
        series_revision=1,
    )


class IngestionServiceTests(unittest.TestCase):
    def test_derived_timeframe_requests_enough_base_bars_and_saves_snapshot(self) -> None:
        provider = FakeProvider()
        store = FakeStore()

        result = IngestionService(provider=provider, store=store).ingest(request())

        self.assertIsNotNone(provider.request)
        assert provider.request is not None
        self.assertEqual(provider.request.timeframe, Timeframe.M15)
        self.assertEqual(provider.request.bars, 30)
        self.assertEqual(result.timeframe, Timeframe.M45)
        self.assertEqual(len(result.bars), 10)
        self.assertEqual(store.saved, [result])

    def test_weekly_ingestion_requires_point_in_time_calendar_adapter(self) -> None:
        with self.assertRaisesRegex(ValueError, "takvim adapter"):
            IngestionService(provider=FakeProvider(), store=FakeStore()).ingest(
                request(Timeframe.W1)
            )

    def test_future_closed_bar_is_not_persisted(self) -> None:
        store = FakeStore()
        service = IngestionService(provider=FakeProvider(future_bar=True), store=store)

        with self.assertRaisesRegex(ValueError, "gelecekte"):
            service.ingest(request(Timeframe.M15))

        self.assertEqual(store.saved, [])


if __name__ == "__main__":
    unittest.main()
