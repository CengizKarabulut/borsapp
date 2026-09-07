import json
import tempfile
import unittest
from pathlib import Path

from src.scan_state import load_state, mark_reported, save_state, select_new

RESULTS = [
    {"ticker": "THYAO", "screens": ["sikisma_hacim"], "setup": "Sıkışma / karar bölgesi"},
    {"ticker": "ASELS", "screens": ["hacim_patlamasi"], "setup": "Trend devamı"},
    {"ticker": "EREGL", "screens": ["basarisiz_kirilim"], "setup": "Destekte reddedilme"},
]


class SelectionTests(unittest.TestCase):
    def test_new_symbols_are_selected_up_to_limit(self) -> None:
        self.assertEqual([item["ticker"] for item in select_new(RESULTS, {}, 2)], ["THYAO", "ASELS"])

    def test_already_reported_symbol_is_skipped(self) -> None:
        reported = mark_reported(RESULTS[:1], {})
        picked = select_new(RESULTS, reported, 3)
        self.assertNotIn("THYAO", [item["ticker"] for item in picked])

    def test_changed_state_is_reported_again(self) -> None:
        """Aynı hisse farklı bir kuruluma geçtiyse yeniden raporlanmalı."""
        reported = mark_reported(RESULTS[:1], {})
        changed = [{**RESULTS[0], "setup": "Trend devamı"}]
        self.assertEqual(len(select_new(changed, reported, 3)), 1)

    def test_zero_limit_disables_reports(self) -> None:
        self.assertEqual(select_new(RESULTS, {}, 0), [])


class StateFileTests(unittest.TestCase):
    def test_state_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state({"THYAO": "a|b"}, path, today="2026-08-19")
            self.assertEqual(load_state(path, today="2026-08-19"), {"THYAO": "a|b"})

    def test_state_resets_on_a_new_day(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state({"THYAO": "a|b"}, path, today="2026-08-18")
            self.assertEqual(load_state(path, today="2026-08-19"), {})

    def test_corrupt_state_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text("bozuk json", encoding="utf-8")
            self.assertEqual(load_state(path, today="2026-08-19"), {})

    def test_missing_file_is_handled(self) -> None:
        self.assertEqual(load_state(Path("/tmp/olmayan_durum.json"), today="2026-08-19"), {})

    def test_saved_payload_carries_the_date(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state({"A": "x"}, path, today="2026-08-19")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["date"], "2026-08-19")


class ScanCardTests(unittest.TestCase):
    def test_card_is_rendered_for_matches(self) -> None:
        from PIL import Image

        from src.scan_card import render_scan_cards

        payload = {
            "requested": 600, "processed": 500, "matched": 2, "filtered_out": 90,
            "error_kinds": {"kisa_gecmis": ["A"]}, "header_line": "19.08.2026 14:30 · 1h tarama",
            "results": [
                {"ticker": "THYAO", "close": 300.5, "rvol": 2.3, "bb_width_percentile": 12,
                 "screens": ["sikisma_hacim"], "setup": "Sıkışma / karar bölgesi", "excess_return_20": 4.2, "notes": []},
                {"ticker": "ASELS", "close": 88.1, "rvol": 5.4, "bb_width_percentile": 84,
                 "screens": ["hacim_patlamasi"], "setup": "Trend devamı", "excess_return_20": -6.1, "notes": ["Geç aşama"]},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            paths = render_scan_cards(payload, Path(directory), "borsapy", 300.0)
            self.assertGreaterEqual(len(paths), 1)
            # Kart genişliği scan_card.render figsize=9.0 x dpi=140 ile sabittir.
            self.assertEqual(Image.open(paths[0]).size[0], 1260)

    def test_card_is_rendered_with_zero_matches(self) -> None:
        from src.scan_card import render_scan_cards

        payload = {"requested": 600, "processed": 500, "matched": 0, "filtered_out": 90, "error_kinds": {}, "results": []}
        with tempfile.TemporaryDirectory() as directory:
            paths = render_scan_cards(payload, Path(directory), "borsapy", 300.0)
            self.assertEqual(len(paths), 1)


if __name__ == "__main__":
    unittest.main()
