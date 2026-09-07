import json
import tempfile
import unittest
from pathlib import Path

from src.bot_settings import (
    SETTINGS,
    apply_change,
    defaults,
    describe,
    load_settings,
    normalize_key,
    save_settings,
    workflow_inputs,
)


class KeyTests(unittest.TestCase):
    def test_known_keys_are_accepted(self) -> None:
        for name in SETTINGS:
            self.assertEqual(normalize_key(name), name)

    def test_aliases_resolve(self) -> None:
        self.assertEqual(normalize_key("RVOL_MIN"), "rvol")
        self.assertEqual(normalize_key("bollinger"), "bant")

    def test_unknown_key_returns_none(self) -> None:
        self.assertIsNone(normalize_key("olmayan"))


class ChangeTests(unittest.TestCase):
    def test_valid_change_is_applied(self) -> None:
        updated, message = apply_change(defaults(), "rvol", "2.0")
        self.assertEqual(updated["rvol"], 2.0)
        self.assertIn("2", message)

    def test_comma_decimal_is_accepted(self) -> None:
        updated, _ = apply_change(defaults(), "rvol", "2,5")
        self.assertEqual(updated["rvol"], 2.5)

    def test_out_of_range_is_rejected(self) -> None:
        """Sınırsız değer taramayı kullanılamaz hale getirir."""
        updated, message = apply_change(defaults(), "rvol", "0.1")
        self.assertIsNone(updated)
        self.assertIn("geçerli aralık", message)

    def test_non_numeric_is_rejected(self) -> None:
        updated, message = apply_change(defaults(), "rvol", "çok")
        self.assertIsNone(updated)
        self.assertIn("Sayı bekleniyordu", message)

    def test_unknown_setting_is_rejected(self) -> None:
        self.assertIsNone(apply_change(defaults(), "olmayan", "1")[0])


class PersistenceTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            values = defaults()
            values["rvol"] = 2.5
            save_settings(values, path)
            self.assertEqual(load_settings(path)["rvol"], 2.5)

    def test_missing_file_returns_defaults(self) -> None:
        self.assertEqual(load_settings(Path("/tmp/olmayan_ayar.json")), defaults())

    def test_corrupt_file_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text("bozuk", encoding="utf-8")
            self.assertEqual(load_settings(path), defaults())

    def test_out_of_range_stored_value_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            path.write_text(json.dumps({"rvol": 999}), encoding="utf-8")
            self.assertEqual(load_settings(path)["rvol"], defaults()["rvol"])


class OutputTests(unittest.TestCase):
    def test_description_marks_changed_values(self) -> None:
        values = defaults()
        values["rvol"] = 2.5
        text = describe(values)
        self.assertIn("değiştirildi", text)
        self.assertIn("/esik rvol", text)

    def test_workflow_inputs_cover_every_setting(self) -> None:
        inputs = workflow_inputs(defaults())
        for setting in SETTINGS.values():
            self.assertIn(setting.workflow_input, inputs)
