from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from market_intelligence.cli import _feature_engine
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.scanning.catalog import load_scanner_catalog

ROOT = Path(__file__).resolve().parents[1]


class ScannerCatalogTests(unittest.TestCase):
    def test_every_scanner_feature_and_dependency_has_a_runtime_provider(self) -> None:
        bindings = load_scanner_catalog(ROOT / "config/scanners.toml")
        registry = _feature_engine(None).registry
        visited: set[str] = set()

        def assert_registered(spec) -> None:
            if spec.identity_hash in visited:
                return
            visited.add(spec.identity_hash)
            provider = registry.resolve(spec)
            for dependency in getattr(provider, "dependencies", ()):
                assert_registered(dependency)

        for binding in bindings:
            for spec in binding.scanner.required_features:
                with self.subTest(scanner=binding.scanner.id, feature=spec.feature_id):
                    assert_registered(spec)

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
                "decision.panel_v645",
            },
        )
        for binding in bindings:
            self.assertEqual(len(binding.ruleset_hash), 64)
            self.assertTrue(
                binding.notification_timeframes.issubset(binding.shadow_timeframes)
            )
        volume = next(b for b in bindings if b.scanner.id == "technical.volume_spike")
        self.assertIn(Timeframe.H1, volume.shadow_timeframes)
        self.assertEqual(volume.notification_timeframes, frozenset())

    def test_notification_requires_verified_parity_evidence(self) -> None:
        source = (ROOT / "config/scanners.toml").read_text(encoding="utf-8")
        altered = source.replace(
            "notification_timeframes = []",
            'notification_timeframes = ["1h"]',
            1,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scanners.toml"
            path.write_text(altered, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "doğrulanmış parity"):
                load_scanner_catalog(path)


if __name__ == "__main__":
    unittest.main()
