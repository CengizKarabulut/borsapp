from __future__ import annotations

import unittest
from pathlib import Path

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scanning.catalog import load_scanner_catalog

ROOT = Path(__file__).resolve().parents[1]


class ScannerCatalogTests(unittest.TestCase):
    def test_all_migrated_scanners_load_from_resolved_toml(self) -> None:
        bindings = load_scanner_catalog(ROOT / "config/scanners.toml")
        self.assertEqual(
            {binding.scanner.id for binding in bindings},
            {
                "technical.decision_zone",
                "technical.exhaustion",
                "technical.extreme_rsi",
                "technical.failed_breakout",
                "technical.squeeze_volume",
                "technical.trend_continuation",
                "technical.volume_spike",
                "signal.macd_positive_cross",
                "signal.smi_macd_positive",
                "signal.smi_macd_positive_volume_confirmed",
                "signal.rsi_momentum_volume",
                "signal.rsi_macd_volume",
                "signal.smi_macd_early",
                "signal.smi_macd_full",
                "signal.sma_macd_volume",
                "signal.ema_trend_volume",
                "ma.near_zone",
            },
        )
        for binding in bindings:
            self.assertEqual(len(binding.ruleset_hash), 64)
            self.assertTrue(
                binding.notification_timeframes.issubset(binding.shadow_timeframes)
            )
        volume = next(b for b in bindings if b.scanner.id == "technical.volume_spike")
        self.assertIn(Timeframe.H1, volume.notification_timeframes)


if __name__ == "__main__":
    unittest.main()
