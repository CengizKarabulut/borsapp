from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import timedelta

from market_intelligence.core.enums import EvaluationStatus
from market_intelligence.features.momentum import (
    MACD_12_26_9, RSI_14, SMI_10_3_3, MacdSnapshot, RsiSnapshot, SmiSnapshot,
)
from market_intelligence.features.trend import (
    INCLUSIVE_VOLUME_SMA_20, LEGACY_TREND_MA_SET,
    InclusiveVolumeSnapshot, LegacyTrendMaSnapshot,
)
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.signal.atc_native_packet import (
    ATC_NATIVE_SIGNAL_IDS, AtcNativeSignalScanner,
)
from tests.test_volume_spike import context, frame


class AtcPineNativeSignalTests(unittest.TestCase):
    def test_all_nine_rules_use_latest_source(self):
        self.assertEqual(len(ATC_NATIVE_SIGNAL_IDS), 9)
        for i, scanner_id in enumerate(ATC_NATIVE_SIGNAL_IDS, 1):
            scanner = AtcNativeSignalScanner(scanner_id)
            self.assertEqual(scanner.rule_number, i)
            self.assertEqual(scanner.version, "2.0.0")
            self.assertFalse(scanner.accepts_partial_bars)

    def test_rule_one_matches_native_packet_without_chart_extra_filters(self):
        source = frame(last_volume=100.0)
        scanner = AtcNativeSignalScanner(ATC_NATIVE_SIGNAL_IDS[0])
        features = {
            MACD_12_26_9.feature_id: MacdSnapshot(
                line=0.5, signal=0.3, histogram=0.2,
                previous_line=0.35, previous_signal=0.35, previous_histogram=0,
            ),
            RSI_14.feature_id: RsiSnapshot(value=55, previous_value=48),
        }
        result = ScannerEngine().run(
            cycle_id="test-cycle", frame=source,
            scanner=scanner, context=context(source, features)
        )
        self.assertEqual(result.evaluation.status, EvaluationStatus.MATCH)
        self.assertEqual(result.findings[0].metrics["atc_rule_number"], 1)
        # The legacy chart overlay demanded additional trend/volume conditions
        # that are absent from the authoritative native alarm packet.

    def test_rule_seven_and_eight_are_mutually_exclusive(self):
        source = frame(last_volume=200.0)
        trend = LegacyTrendMaSnapshot(
            close=10.0,
            sma={200: 9.0},
            ema={}, previous_ema={},
        )
        features = {
            MACD_12_26_9.feature_id: MacdSnapshot(
                line=-0.2, signal=-0.3, histogram=-0.1,
                previous_line=-0.3, previous_signal=-0.2, previous_histogram=-0.2
            ),
            SMI_10_3_3.feature_id: SmiSnapshot(
                value=-10, signal=-12, previous_value=-13, previous_signal=-11
            ),
            LEGACY_TREND_MA_SET.feature_id: trend,
            INCLUSIVE_VOLUME_SMA_20.feature_id: InclusiveVolumeSnapshot(
                observed_volume=200, mean_volume=100, ratio=2
            ),
        }
        # G/H both need >=200 bars for MA200 availability, but the scorer
        # consumes canonical frame quality separately from the snapshot.
        additional = []
        last = source.bars[-1]
        for i in range(180):
            opened = last.close_time + timedelta(hours=i)
            additional.append(replace(last, open_time=opened, close_time=opened + timedelta(hours=1)))
        extended = replace(source, bars=source.bars + tuple(additional), snapshot_id="longer")
        statuses = []
        for rule in (7, 8):
            scanner = AtcNativeSignalScanner(ATC_NATIVE_SIGNAL_IDS[rule - 1])
            result = ScannerEngine().run(
                cycle_id="test-cycle", frame=extended,
                scanner=scanner, context=context(extended, features)
            )
            statuses.append(result.evaluation.status)
        self.assertEqual(statuses.count(EvaluationStatus.MATCH), 1)

    def test_unknown_and_unconfirmed_are_not_silent_no_match(self):
        scanner = AtcNativeSignalScanner(ATC_NATIVE_SIGNAL_IDS[0])
        source = frame()
        engine = ScannerEngine()
        missing = engine.run(
            cycle_id="x", frame=source, scanner=scanner, context=context(source)
        )
        self.assertEqual(missing.evaluation.status, EvaluationStatus.UNKNOWN)
        partial = replace(source, is_partial=True)
        blocked = engine.run(
            cycle_id="x", frame=partial, scanner=scanner, context=context(partial)
        )
        self.assertEqual(blocked.evaluation.status, EvaluationStatus.UNKNOWN)
        self.assertEqual(blocked.evaluation.error_code, "partial_bar_rejected")


if __name__ == "__main__":
    unittest.main()
