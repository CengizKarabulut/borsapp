from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from market_intelligence.application.scan_frame import ScanFrameCoordinator
from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.delivery.telegram.config import DeliveryMode, TelegramSettings, TopicKind
from market_intelligence.features.ma import UnavailableMaResearchProvider
from market_intelligence.features.momentum import MacdProvider, RsiProvider
from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.features.volume import RelativeVolume20Provider
from market_intelligence.persistence.postgres.confluence import PersistedConfluence
from market_intelligence.persistence.postgres.scan_store import PersistedScan
from market_intelligence.persistence.postgres.state_store import PersistedStateRun
from market_intelligence.scanning.catalog import ScannerBinding
from market_intelligence.scanning.contracts import Finding
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


class ConfluenceStore:
    def __init__(self):
        self.calls = []

    def persist(self, **kwargs):
        self.calls.append(kwargs)
        return PersistedConfluence("report-1", int(kwargs["envelope"] is not None))


class AlwaysMatchScanner:
    version = "1"
    result_kind = ResultKind.EVENT
    required_features = ()
    accepts_partial_bars = False

    def __init__(self, scanner_id: str, family: str, timeframe) -> None:
        self.id = scanner_id
        self.family = family
        self.supported_timeframes = {timeframe}

    def prefilter(self, frame, context) -> bool:
        return True

    def evaluate(self, frame, context):
        return (
            Finding(
                finding_key=self.id,
                instrument_id=frame.instrument_id,
                symbol_at_event=frame.symbol_at_snapshot,
                timeframe=frame.timeframe,
                scanner_id=self.id,
                scanner_version=self.version,
                ruleset_hash=context.ruleset_hash,
                kind=self.result_kind,
                bar_time=context.bar_close_time,
                direction=Direction.BULLISH,
            ),
        )


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

    def test_two_matching_families_persist_and_route_strict_confluence(self) -> None:
        source = frame()
        event_store = EventStore()
        confluence_store = ConfluenceStore()
        bindings = tuple(
            ScannerBinding(
                scanner=AlwaysMatchScanner(f"{family}.test", family, source.timeframe),
                ruleset_hash=f"rules-{family}",
                shadow_timeframes=frozenset({source.timeframe}),
                notification_timeframes=frozenset({source.timeframe}),
            )
            for family in ("signal", "technical")
        )
        coordinator = ScanFrameCoordinator(
            feature_engine=engine(),
            event_store=event_store,
            state_store=StateStore(),
            telegram_settings=settings(DeliveryMode.LIVE),
            confluence_store=confluence_store,
        )

        result = coordinator.run(
            cycle_id="cycle-1",
            frame=source,
            bindings=bindings,
            evaluation_time=datetime(2026, 9, 7, 18, 5, tzinfo=ISTANBUL),
        )

        self.assertEqual(result.confluence_count, 1)
        self.assertEqual(result.outbox_count, 3)
        report = confluence_store.calls[0]["report"]
        self.assertTrue(report.qualifies)
        self.assertEqual(report.families, ("signal", "technical"))
        envelope = confluence_store.calls[0]["envelope"]
        self.assertEqual(envelope.message_thread_id, 11)
        self.assertIn("[CONFLUENCE]", envelope.payload["text"])

    def test_catch_up_persists_confluence_without_notification(self) -> None:
        source = frame()
        confluence_store = ConfluenceStore()
        bindings = tuple(
            ScannerBinding(
                scanner=AlwaysMatchScanner(f"{family}.test", family, source.timeframe),
                ruleset_hash=f"rules-{family}",
                shadow_timeframes=frozenset({source.timeframe}),
                notification_timeframes=frozenset({source.timeframe}),
            )
            for family in ("signal", "technical")
        )
        coordinator = ScanFrameCoordinator(
            feature_engine=engine(),
            event_store=EventStore(),
            state_store=StateStore(),
            telegram_settings=settings(DeliveryMode.LIVE),
            confluence_store=confluence_store,
        )

        coordinator.run(
            cycle_id="cycle-1",
            frame=source,
            bindings=bindings,
            evaluation_time=datetime(2026, 9, 7, 18, 5, tzinfo=ISTANBUL),
            allow_notifications=False,
        )

        self.assertIsNone(confluence_store.calls[0]["envelope"])

    def test_confluence_respects_each_scanner_notification_timeframe(self) -> None:
        source = frame()
        confluence_store = ConfluenceStore()
        bindings = tuple(
            ScannerBinding(
                scanner=AlwaysMatchScanner(f"{family}.test", family, source.timeframe),
                ruleset_hash=f"rules-{family}",
                shadow_timeframes=frozenset({source.timeframe}),
                notification_timeframes=(
                    frozenset({source.timeframe})
                    if family == "signal"
                    else frozenset()
                ),
            )
            for family in ("signal", "technical")
        )
        coordinator = ScanFrameCoordinator(
            feature_engine=engine(),
            event_store=EventStore(),
            state_store=StateStore(),
            telegram_settings=settings(DeliveryMode.LIVE),
            confluence_store=confluence_store,
        )

        coordinator.run(
            cycle_id="cycle-1",
            frame=source,
            bindings=bindings,
            evaluation_time=datetime(2026, 9, 7, 18, 5, tzinfo=ISTANBUL),
        )

        self.assertIsNone(confluence_store.calls[0]["envelope"])


if __name__ == "__main__":
    unittest.main()
