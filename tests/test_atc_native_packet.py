from __future__ import annotations

import hashlib
import math
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from market_intelligence.core.enums import EvaluationStatus, PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.atc_native import (
    ATC_NATIVE_PACKET,
    AtcNativePacketProvider,
    calculate_native_packet,
)
from market_intelligence.features.registry import FeatureEngine, FeatureRegistry
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.scanning.pipeline import ScanPipeline
from market_intelligence.scanning.signal.atc_native_packet import (
    ATC_NATIVE_SIGNAL_IDS,
    ATC_SCRIPT_SHA256,
    AtcNativeSignalScanner,
)
from tests.test_volume_spike import frame


ROOT = Path(__file__).resolve().parents[1]


def price_frame(prices: list[float]) -> CanonicalFrame:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    candles = []
    for i, close in enumerate(prices):
        opened = start + timedelta(days=i)
        candles.append(
            CanonicalBar(
                open_time=opened,
                close_time=opened + timedelta(hours=1),
                open=close, high=close + 2.0, low=close - 2.0,
                close=close, volume=1000.0,
            )
        )
    return CanonicalFrame(
        instrument_id="example-1", symbol_at_snapshot="ATC",
        market="BIST", timeframe=Timeframe.D1, snapshot_id="snap-1",
        series_revision=1, price_basis=PriceBasis.RAW, source="fixture",
        bars=tuple(candles),
    )


def pipeline() -> ScanPipeline:
    registry = FeatureRegistry()
    registry.register(AtcNativePacketProvider())
    return ScanPipeline(FeatureEngine(registry))


def context(source):
    from market_intelligence.scanning.contracts import ScanContext

    return ScanContext(
        evaluation_time=source.through_bar_time + timedelta(seconds=5),
        bar_close_time=source.through_bar_time,
        market_session_id="BIST:test",
        calendar_version="bist-session-v1", ruleset_hash="atc-test",
    )


class AtcPineNativeSignalTests(unittest.TestCase):
    def test_exact_user_source_was_preserved_byte_for_byte_in_crlf_form(self):
        source = ROOT / "docs/reference/ATC_TV200_18_TARAMA_20261012.pine"
        canonical = (source.read_text(encoding="utf-8").rstrip("\n") + "\n").replace("\n", "\r\n")
        self.assertEqual(hashlib.sha256(canonical.encode("utf-8")).hexdigest(), ATC_SCRIPT_SHA256)

    def test_all_nine_rules_use_one_shared_native_packet_feature(self):
        self.assertEqual(len(ATC_NATIVE_SIGNAL_IDS), 9)
        for i, scanner_id in enumerate(ATC_NATIVE_SIGNAL_IDS, 1):
            scanner = AtcNativeSignalScanner(scanner_id)
            self.assertEqual(scanner.rule_number, i)
            self.assertEqual(scanner.version, "2.0.0")
            self.assertEqual(scanner.required_features, (ATC_NATIVE_PACKET,))
            self.assertFalse(scanner.accepts_partial_bars)

    def test_old_history_outside_600_bars_cannot_affect_current_packet(self):
        last600 = [100.0 + i * 0.04 + 3 * math.sin(i / 9) for i in range(600)]
        source600 = price_frame(last600)
        source800 = price_frame([30.0] * 200 + last600)
        a = calculate_native_packet(source600)
        b = calculate_native_packet(source800)
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertEqual(a, b)
        self.assertEqual(len(a.known), 9)
        self.assertTrue(all(a.known))

    def test_insufficient_history_returns_unknown_not_false(self):
        source = frame()
        scan = AtcNativeSignalScanner(ATC_NATIVE_SIGNAL_IDS[0])
        run = pipeline().run(cycle_id="pilot", frame=source, scanner=scan, context=context(source))
        self.assertEqual(run.scan.evaluation.status, EvaluationStatus.UNKNOWN)
        self.assertEqual(run.scan.evaluation.error_code, "scanner_input_unavailable")

    def test_available_no_match_does_not_become_unknown(self):
        source = price_frame([60.0 + i * 0.01 for i in range(250)])
        scan = AtcNativeSignalScanner(ATC_NATIVE_SIGNAL_IDS[8])
        run = pipeline().run(cycle_id="pilot", frame=source, scanner=scan, context=context(source))
        self.assertIn(run.scan.evaluation.status, (EvaluationStatus.MATCH, EvaluationStatus.NO_MATCH))
        self.assertEqual(run.features.unavailable, ())

    def test_invalid_price_and_partial_bar_are_unknown(self):
        source = frame()
        partial = source.__class__(
            **{**source.__dict__, "is_partial": True}
        )
        result = pipeline().run(
            cycle_id="pilot", frame=partial,
            scanner=AtcNativeSignalScanner(ATC_NATIVE_SIGNAL_IDS[0]), context=context(partial),
        )
        self.assertEqual(result.scan.evaluation.status, EvaluationStatus.UNKNOWN)
        self.assertEqual(result.scan.evaluation.error_code, "partial_bar_rejected")


if __name__ == "__main__":
    unittest.main()
