from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.application.scan_frame import ScanFrameCoordinator
from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings, TopicKind
from market_intelligence.features.ma import UnavailableMaResearchProvider
from market_intelligence.features.momentum import MacdProvider, RsiProvider
from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.features.volume import RelativeVolume20Provider
from market_intelligence.persistence.postgres.scan_store import PersistedScan
from market_intelligence.persistence.postgres.state_store import PersistedStateRun
from market_intelligence.scanning.catalog import ScannerBinding
from market_intelligence.scanning.technical.volume_spike import (
    TechnicalVolumeSpikeScanner,
    VolumeSpikeConfig,
)
from tests.test_volume_spike import frame

ISTANBUL = ZoneInfo("Europe/Istanbul")


class EventStore:
    def __init__(self):
        self.envelopes = []

    def persist_event_run(self, run, envelopes=None):
        self.envelopes.append(dict(envelopes or {}))
        return PersistedScan("evaluation-1", tuple(f"event-{i}" for i in range(len(run.findings))), len(envelopes or {}))


class StateStore:
    def persist_state_run(self, run, envelopes=None, **kwargs):
        return PersistedStateRun("evaluation-2", (), (), 0)


def settings(mode: DeliveryMode) -> TelegramSettings:
    return TelegramSettings(
        bot_token="secret",
        chat_id=-100123,
        allowed_user_ids=frozenset({42}),
        topic_ids={kind: index + 10 for index, kind in enumerate(TopicKind)},
        delivery_mode=mode,
    )


def engine() -> FeatureEngine:
    registry = FeatureRegistry()
    for provider in (
        RelativeVolume20Provider(),
        MacdProvider(),
        RsiProvider(),
        UnavailableMaResearchProvider(),
    ):
        registry.register(provider)
    return FeatureEngine(registry)


class ScanFrameCoordinatorTests(unittest.TestCase):
    def test_disabled_delivery_never_accumulates_future_outbox_flood(self) -> None:
        event_store = EventStore()
        scanner = TechnicalVolumeSpikeScanner(
            VolumeSpikeConfig(
                relative_volume_threshold=1,
                minimum_average_turnover=0,
                minimum_price=0,
            )
        )
        source = frame()
        binding = ScannerBinding(
            scanner=scanner,
            ruleset_hash="rules",
            shadow_timeframes=frozenset({source.timeframe}),
            notification_timeframes=frozenset({source.timeframe}),
        )
        coordinator = ScanFrameCoordinator(
            feature_engine=engine(),
            event_store=event_store,
            state_store=StateStore(),
            telegram_settings=settings(DeliveryMode.DISABLED),
        )

        result = coordinator.run(
            cycle_id="cycle-1",
            frame=source,
            bindings=(binding,),
            evaluation_time=datetime(2026, 9, 7, 18, 5, tzinfo=ISTANBUL),
        )

        self.assertEqual(result.outbox_count, 0)
        self.assertEqual(event_store.envelopes, [{}])


if __name__ == "__main__":
    unittest.main()
