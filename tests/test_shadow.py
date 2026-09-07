from __future__ import annotations

import unittest

from market_intelligence.features.volume import RELATIVE_VOLUME_20, calculate_volume_activity
from market_intelligence.scanning.engine import ScannerEngine
from market_intelligence.scanning.technical.volume_spike import (
    TechnicalVolumeSpikeScanner,
    VolumeSpikeConfig,
)
from market_intelligence.shadow.compare import ShadowCategory, ShadowComparator
from market_intelligence.shadow.legacy_volume_spike import LegacyVolumeSpikeContractAdapter
from tests.test_volume_spike import context, frame


class ShadowComparisonTests(unittest.TestCase):
    def test_volume_spike_agrees_on_same_snapshot_with_alias(self) -> None:
        source = frame()
        legacy = LegacyVolumeSpikeContractAdapter(
            minimum_average_turnover=0
        ).evaluate(source)
        new = ScannerEngine().run(
            cycle_id="cycle",
            frame=source,
            scanner=TechnicalVolumeSpikeScanner(
                VolumeSpikeConfig(minimum_average_turnover=0)
            ),
            context=context(
                source,
                {RELATIVE_VOLUME_20.feature_id: calculate_volume_activity(source)},
            ),
        )
        comparison = ShadowComparator(
            {"hacim_patlamasi": "volume-spike"}
        ).compare(legacy, new)
        self.assertEqual(comparison.category, ShadowCategory.AGREE_MATCH)

    def test_different_snapshot_is_rejected(self) -> None:
        source = frame()
        legacy = LegacyVolumeSpikeContractAdapter(
            minimum_average_turnover=0
        ).evaluate(source)
        new = ScannerEngine().run(
            cycle_id="cycle",
            frame=source,
            scanner=TechnicalVolumeSpikeScanner(
                VolumeSpikeConfig(minimum_average_turnover=0)
            ),
            context=context(
                source,
                {RELATIVE_VOLUME_20.feature_id: calculate_volume_activity(source)},
            ),
        )
        altered = type(legacy)(
            snapshot_id="other",
            scanner_id=legacy.scanner_id,
            status=legacy.status,
            finding_keys=legacy.finding_keys,
        )
        with self.assertRaisesRegex(ValueError, "aynı snapshot"):
            ShadowComparator().compare(altered, new)


if __name__ == "__main__":
    unittest.main()
