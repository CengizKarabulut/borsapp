from __future__ import annotations

import os
import unittest

from market_intelligence.shadow.registry import ShadowAdapterRegistry
from tests.test_volume_spike import frame


@unittest.skipUnless(os.environ.get("TEST_DATABASE_URL"), "runtime integration job only")
class LegacyShadowAdapterIntegrationTests(unittest.TestCase):
    def test_real_signal_and_technical_legacy_engines_execute_offline_frame(self) -> None:
        registry = ShadowAdapterRegistry()
        source = frame()
        signal = registry.adapter_for("signal.macd_positive_cross")
        technical = registry.adapter_for("technical.volume_spike")
        assert signal is not None and technical is not None

        signal_result = signal.evaluate(source)
        technical_result = technical.evaluate(source)

        self.assertEqual(signal_result.snapshot_id, source.snapshot_id)
        self.assertEqual(technical_result.snapshot_id, source.snapshot_id)
        self.assertFalse(
            any(value.startswith("legacy_error:") for value in signal_result.diagnostics),
            signal_result.diagnostics,
        )
        self.assertFalse(
            any(value.startswith("legacy_error:") for value in technical_result.diagnostics),
            technical_result.diagnostics,
        )
