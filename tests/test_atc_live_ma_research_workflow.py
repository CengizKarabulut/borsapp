"""Production scanner deploy contract for real 630-stock MA research."""
from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class EphemeralLiveResearchSettingsTests(unittest.TestCase):
    def test_real_telegram_scans_compute_original_closed_bar_ma_research(self):
        content = (ROOT / ".github/workflows/atc-ephemeral-six-scans.yml").read_text(
            encoding="utf-8",
        )
        job = content.split("  real-scan-and-telegram:", 1)[1].split(
            "  confirmed-kesisim:", 1
        )[0]
        self.assertIn('ATC_MA_RESEARCH_ON_DEMAND: "1"', job)
        self.assertIn("python -m scripts.atc_ephemeral_universe", job)
        self.assertIn("scan-due --universe ATC_630", job)
        self.assertIn("python -m scripts.atc_timeframe_visuals", job)
        # Explicitly do not enable fallback for unrelated background jobs.
        self.assertNotIn("ATC_MA_RESEARCH_ON_DEMAND", content.split("jobs:", 1)[0])


if __name__ == "__main__":
    unittest.main()
