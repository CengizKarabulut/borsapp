import unittest
from datetime import UTC, datetime

from market_intelligence.application.full_scan_pdf import render_full_scan_pdf


class FullPdfTests(unittest.TestCase):
    def test_more_than_twenty_findings_and_multiple_timeframes(self):
        from unittest.mock import patch

        from reportlab.platypus import SimpleDocTemplate

        stories = []
        original = SimpleDocTemplate.build

        def capture(doc, story, **kwargs):
            stories.extend(
                cell.text
                for flow in story
                if hasattr(flow, "_cellvalues")
                for row in flow._cellvalues
                for cell in row
                if hasattr(cell, "text")
            )
            return original(doc, story, **kwargs)

        sections = [
            dict(
                timeframe=tf,
                target="2026-09-11",
                expected=30,
                summary=[("test", 30, 25, 2)],
                scanners=["test"],
                details=[
                    dict(
                        symbol=f"TEST{i:02d}",
                        scanner="test",
                        direction="bullish",
                        plan={"reason": "snapshot_missing", "scenarios": []},
                    )
                    for i in range(25)
                ],
            )
            for tf in ("1h", "1wk")
        ]
        with patch.object(SimpleDocTemplate, "build", capture):
            pdf = render_full_scan_pdf(sections, datetime(2026, 9, 13, tzinfo=UTC))
        texts = stories
        self.assertEqual(texts.count("TEST24 / test"), 2)
        self.assertEqual(texts.count("TEST00 / test"), 2)
        self.assertTrue(pdf.startswith(b"%PDF"))
