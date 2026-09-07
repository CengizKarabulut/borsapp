import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from src.watch_alerts import (
    MAX_WATCHED,
    Watch,
    add_watch,
    check_break,
    describe,
    latest_confirmed_close,
    load_watches,
    remove_watch,
    save_watches,
    select_watch_levels,
)


def watch(ticker: str = "THYAO", upper: float = 310.0, lower: float = 290.0) -> Watch:
    return Watch(
        ticker=ticker,
        interval="1d",
        upper=upper,
        lower=lower,
        setup="Sıkışma / karar bölgesi",
        added_at="2026-08-20T10:00",
        reference_close=300.0,
        last_close=300.0,
    )


class BreakTests(unittest.TestCase):
    def test_close_above_upper_triggers_on_cross(self) -> None:
        message = check_break(watch(), 312.0)
        self.assertIn("yukarı eşik aşıldı", message)
        self.assertIn("312", message)
        self.assertIn("300", message)

    def test_close_below_lower_triggers_on_cross(self) -> None:
        self.assertIn("aşağı eşik aşıldı", check_break(watch(), 288.0))

    def test_close_inside_range_is_silent(self) -> None:
        self.assertEqual(check_break(watch(), 300.0), "")

    def test_staying_above_does_not_repeat(self) -> None:
        item = watch()
        self.assertIn("yukarı eşik aşıldı", check_break(item, 312.0))
        item.triggered = "2026-08-20T11:00"
        self.assertEqual(check_break(item, 320.0), "")

    def test_return_inside_rearms_and_second_cross_alerts(self) -> None:
        item = watch()
        self.assertIn("yukarı eşik aşıldı", check_break(item, 312.0))
        item.triggered = "2026-08-20T11:00"
        self.assertEqual(check_break(item, 305.0), "")
        self.assertEqual(item.last_event, "")
        second = check_break(item, 315.0)
        self.assertIn("yukarı eşik aşıldı", second)

    def test_lower_side_rearms_after_return_inside(self) -> None:
        item = watch()
        self.assertIn("aşağı eşik aşıldı", check_break(item, 288.0))
        self.assertEqual(check_break(item, 285.0), "")
        self.assertEqual(check_break(item, 300.0), "")
        self.assertIn("aşağı eşik aşıldı", check_break(item, 287.0))

    def test_old_triggered_timestamp_does_not_permanently_lock_watch(self) -> None:
        item = watch()
        item.triggered = "2026-08-20T11:00"
        self.assertIn("yukarı eşik aşıldı", check_break(item, 312.0))

    def test_unknown_previous_close_is_initialized_without_false_alert(self) -> None:
        item = Watch(
            ticker="LEGACY",
            interval="1d",
            upper=310.0,
            lower=290.0,
            setup="",
            added_at="2026-08-20T10:00",
        )
        self.assertEqual(check_break(item, 320.0), "")
        self.assertEqual(item.last_close, 320.0)

    def test_alert_states_it_is_not_advice(self) -> None:
        self.assertIn("önerisi değildir", check_break(watch(), 312.0))


class LevelSelectionTests(unittest.TestCase):
    @patch("src.watch_alerts._confirmed_pivot_candidates")
    def test_broken_old_low_above_price_becomes_upper_not_lower(self, pivots) -> None:
        index = pd.date_range("2026-08-01", periods=30, freq="D")
        data = pd.DataFrame(
            {
                "High": [22.0] * 30,
                "Low": [20.0] * 30,
                "Close": [21.0] * 30,
            },
            index=index,
        )
        pivots.return_value = [
            (27.98, "swing_low", 10),
            (19.50, "swing_low", 18),
            (40.50, "swing_high", 12),
        ]

        levels = select_watch_levels(
            data,
            "BIST",
            "1d",
            now=datetime(2026, 9, 6, 12, 0, tzinfo=ZoneInfo("Europe/Istanbul")),
        )

        self.assertEqual(levels["reference_close"], 21.0)
        self.assertEqual(levels["lower"], 19.50)
        self.assertEqual(levels["upper"], 27.98)
        self.assertIn("reclaim", levels["upper_source"])
        self.assertLess(levels["lower"], levels["reference_close"])
        self.assertLess(levels["reference_close"], levels["upper"])

    def test_live_daily_bar_is_not_treated_as_confirmed_close(self) -> None:
        data = pd.DataFrame(
            {
                "High": [21.0, 26.0],
                "Low": [19.0, 20.0],
                "Close": [20.0, 25.0],
            },
            index=pd.to_datetime(["2026-09-04", "2026-09-07"]),
        )
        close, bar_time = latest_confirmed_close(
            data,
            "BIST",
            "1d",
            now=datetime(2026, 9, 7, 12, 0, tzinfo=ZoneInfo("Europe/Istanbul")),
        )
        self.assertEqual(close, 20.0)
        self.assertTrue(bar_time.startswith("2026-09-04"))

    def test_add_rejects_contradictory_thresholds_when_reference_exists(self) -> None:
        item = watch(upper=40.50, lower=27.98)
        item.reference_close = 21.0
        updated, message = add_watch({}, item)
        self.assertIsNone(updated)
        self.assertIn("oluşturulmadı", message)

    def test_add_initializes_last_close_from_reference(self) -> None:
        item = watch()
        item.last_close = float("nan")
        updated, _ = add_watch({}, item)
        self.assertEqual(updated["THYAO"].last_close, 300.0)


class ListTests(unittest.TestCase):
    def test_add_and_remove(self) -> None:
        watches, message = add_watch({}, watch())
        self.assertIn("THYAO", watches)
        self.assertIn("takibe alındı", message)
        watches, message = remove_watch(watches, "thyao")
        self.assertEqual(watches, {})
        self.assertIn("takipten çıkarıldı", message)

    def test_existing_symbol_is_updated_not_duplicated(self) -> None:
        watches, _ = add_watch({}, watch())
        watches, message = add_watch(watches, watch(upper=320.0))
        self.assertEqual(len(watches), 1)
        self.assertIn("güncellendi", message)

    def test_capacity_is_enforced(self) -> None:
        watches = {f"AAA{index:02d}": watch(f"AAA{index:02d}") for index in range(MAX_WATCHED)}
        updated, message = add_watch(watches, watch("YENIX"))
        self.assertIsNone(updated)
        self.assertIn("dolu", message)

    def test_removing_missing_symbol_is_reported(self) -> None:
        self.assertIsNone(remove_watch({}, "YOKXX")[0])

    def test_empty_description_guides_the_user(self) -> None:
        self.assertIn("/takip THYAO", describe({}))


class PersistenceTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch.json"
            original = watch()
            original.last_event = "upper"
            save_watches({"THYAO": original}, path)
            loaded = load_watches(path)
            self.assertEqual(loaded["THYAO"].upper, 310.0)
            self.assertEqual(loaded["THYAO"].last_close, 300.0)
            self.assertEqual(loaded["THYAO"].last_event, "upper")

    def test_legacy_record_without_new_fields_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch.json"
            path.write_text(
                '{"ZGYO": {"ticker": "ZGYO", "interval": "1d", "upper": 40.5, '
                '"lower": 27.98, "setup": "", "added_at": "2026-09-06T10:00"}}',
                encoding="utf-8",
            )
            loaded = load_watches(path)
            self.assertIn("ZGYO", loaded)
            self.assertTrue(pd.isna(loaded["ZGYO"].reference_close))
            self.assertTrue(pd.isna(loaded["ZGYO"].last_close))

    def test_corrupt_file_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch.json"
            path.write_text("bozuk", encoding="utf-8")
            self.assertEqual(load_watches(path), {})

    def test_malformed_entry_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "watch.json"
            path.write_text('{"AAA": {"ticker": "AAA"}}', encoding="utf-8")
            self.assertEqual(load_watches(path), {})


if __name__ == "__main__":
    unittest.main()
