import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_intelligence.application.command_jobs import CommandJob
from market_intelligence.cli import _command_job_executor
from market_intelligence.delivery.telegram.commands import CommandName
from market_intelligence.settings import ApplicationSettings
from tests.test_telegram_routing import environment


class ChartOutboxTests(unittest.TestCase):
    def test_rendered_document_uses_durable_outbox(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "chart.png"
            path.write_bytes(b"png-content")
            values = {
                **environment(),
                "DATABASE_URL": "postgresql://unused/unused",
                "BORSAPP_ARTIFACT_ROOT": folder,
            }
            settings = ApplicationSettings.from_mapping(values)
            execute = _command_job_executor(
                settings, timeframe="1h", bars=500, scanners_path=Path("config/scanners.toml")
            )
            job = CommandJob("job-1", CommandName.CHART, "ASELS", 1, 20, 1)
            with patch(
                "market_intelligence.cli.render_chart_documents",
                return_value=(({"path": path, "timeframe": "1d", "caption": "Grafik"},), ()),
            ):
                output = execute(job)
            self.assertEqual(len(output.envelopes), 1)
            self.assertEqual(output.envelopes[0].payload["_method"], "sendDocument")
            self.assertEqual(output.envelopes[0].payload["document_base64"], "cG5nLWNvbnRlbnQ=")
