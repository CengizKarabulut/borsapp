from __future__ import annotations

import unittest

from market_intelligence.shadow.registry import adapter_for, coverage_report


class ShadowRegistryTests(unittest.TestCase):
    def test_all_signal_and_technical_scanners_have_real_legacy_adapter(self) -> None:
        scanner_ids = (
            "technical.squeeze_volume",
            "technical.volume_spike",
            "technical.extreme_rsi",
            "technical.failed_breakout",
            "technical.decision_zone",
            "technical.trend_continuation",
            "technical.exhaustion",
            "signal.macd_positive_cross",
            "signal.smi_macd_positive",
            "signal.smi_macd_positive_volume_confirmed",
            "signal.rsi_momentum_volume",
            "signal.rsi_macd_volume",
            "signal.smi_macd_early",
            "signal.smi_macd_full",
            "signal.sma_macd_volume",
            "signal.ema_trend_volume",
        )
        self.assertTrue(all(mapped for _scanner_id, mapped in coverage_report(scanner_ids)))
        for scanner_id in scanner_ids:
            adapter = adapter_for(scanner_id)
            self.assertIsNotNone(adapter)
            assert adapter is not None
            self.assertTrue(
                "screener.py" in adapter.legacy_reference
                or "signal_parity.py" in adapter.legacy_reference
            )
