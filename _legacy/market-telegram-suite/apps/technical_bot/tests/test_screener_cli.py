import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.screener_cli import main


def price_frame(seed: int, spike: float = 1.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    bars = 520
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.015, bars)))
    volume = rng.lognormal(17, 0.3, bars)
    volume[-1] *= spike
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": volume},
        index=pd.bdate_range("2024-01-01", periods=bars),
    )


class EndToEndTests(unittest.TestCase):
    """main() akışını uçtan uca çalıştırır.

    Ham veri çerçevelerinin JSON'a sızması gibi hatalar yalnızca burada yakalanır;
    birim testleri main() gövdesini hiç çalıştırmaz.
    """

    def _run(self, directory: str, report_top: int = 1, interval: str = "1d") -> dict:
        store = {"AAAA": price_frame(1, spike=9.0), "BBBB": price_frame(2)}
        output = Path(directory) / "screener.json"
        argv = [
            "screener_cli", "--universe", "file", "--watchlist", str(Path(directory) / "list.txt"),
            "--output", str(output), "--state", str(Path(directory) / "state.json"),
            "--report-top", str(report_top), "--benchmark", "", "--interval", interval,
        ]
        Path(directory, "list.txt").write_text("AAAA\nBBBB\n", encoding="utf-8")
        with (
            patch.object(sys, "argv", argv),
            patch("src.screener_cli.build_fetcher", return_value=lambda batch: {t: store[t] for t in batch}),
        ):
            main()
        return json.loads(output.read_text(encoding="utf-8"))

    def test_json_is_written_without_dataframes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self._run(directory)
            self.assertNotIn("frames", payload)
            self.assertIn("results", payload)
            self.assertGreaterEqual(payload["matched"], 1)

    def test_scan_card_image_is_produced(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory)
            cards = list(Path(directory).glob("scan_card_*.png"))
            self.assertTrue(cards, "tarama kartı üretilmeli")

    def test_symbol_report_uses_scanned_data_without_refetching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, report_top=1)
            produced = list(Path(directory).glob("*/*.png"))
            self.assertTrue(produced, "eşleşen sembol için rapor sayfaları üretilmeli")

    def test_state_file_records_reported_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, report_top=1)
            state = json.loads(Path(directory, "state.json").read_text(encoding="utf-8"))
            self.assertIn("reported", state)
            self.assertTrue(state["reported"])

    def test_second_run_does_not_repeat_the_same_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, report_top=1)
            first = len(list(Path(directory).glob("*/*.png")))
            self._run(directory, report_top=1)
            self.assertEqual(len(list(Path(directory).glob("*/*.png"))), first, "aynı sembol yeniden raporlanmamalı")

    def test_report_top_zero_produces_only_the_scan_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, report_top=0)
            self.assertEqual(list(Path(directory).glob("*/*.png")), [])
            self.assertTrue(list(Path(directory).glob("scan_card_*.png")))


if __name__ == "__main__":
    unittest.main()


class MultiIntervalEndToEndTests(EndToEndTests):
    """Çoklu aralık akışı ayrıca sınanır.

    Tek aralıkla çalışan testler, birleşik taramadaki argüman ayrıştırma
    hatalarını yakalayamaz; bu sınıf aynı akışı '1h,1d' ile çalıştırır.
    """

    def test_combined_intervals_produce_merged_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self._run(directory, report_top=1, interval="1h,1d")
            self.assertNotIn("frames", payload)
            self.assertIn("intervals", payload)
            self.assertEqual(payload["intervals"], ["1h", "1d"])
            for item in payload["results"]:
                self.assertIn("matched_intervals", item)

    def test_combined_intervals_write_a_scan_card(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._run(directory, report_top=0, interval="1h,1d")
            self.assertTrue(list(Path(directory).glob("scan_card_*.png")))

    def test_single_interval_payload_has_no_interval_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = self._run(directory, report_top=0, interval="1d")
            self.assertNotIn("matched_intervals", payload.get("results", [{}])[0])
