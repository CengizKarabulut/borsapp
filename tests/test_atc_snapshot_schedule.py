from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from scripts.atc_snapshot_schedule import (
    CHAT,
    LEDGER_SCHEMA,
    SUPPORTED_TIMEFRAMES,
    TOPICS,
    load_delivered,
    main,
    plan,
    validate_delivery_state,
)

IST = ZoneInfo("Europe/Istanbul")


class Calendar:
    def __init__(self, *, holidays=(), half_days=()):
        self.holidays = set(holidays)
        self.half_days = set(half_days)

    def sessions(self, start, end):
        return tuple(start + timedelta(days=offset)
                     for offset in range((end - start).days + 1)
                     if (start + timedelta(days=offset)).weekday() < 5
                     and start + timedelta(days=offset) not in self.holidays)

    def session_bounds(self, day):
        return (datetime.combine(day, time(10), IST),
                datetime.combine(day, time(12, 30) if day in self.half_days else time(18), IST))


def clock(day=20, hour=11, minute=7):
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


def acknowledged(entry):
    return {
        "schema": LEDGER_SCHEMA, **entry, "sent": True, "packet_sha256": "a" * 64,
        "receipt": {"status": "sent", "chat_id": CHAT,
                    "topic_id": TOPICS[entry["timeframe"]], "packet_sha256": "a" * 64,
                    "acknowledged": {"text": 1, "photo": 2, "csv": 3}},
    }


def entries(result):
    return {entry["timeframe"]: entry for entry in result["entries"]}


class SnapshotScheduleTests(unittest.TestCase):
    def setUp(self):
        self.calendar = Calendar()

    def run_plan(self, now, **kwargs):
        return plan(now, calendar=self.calendar, **kwargs)

    def baseline(self):
        # A genuine completed previous-session watermark permits exact tests
        # of only today's newly due slots without replaying previous sessions.
        previous = self.run_plan(clock(day=19, hour=18, minute=30))
        return {tf: acknowledged(item) for tf, item in entries(previous).items()}

    def test_before_first_dispatch_does_not_claim_future_closed_bars(self):
        result = self.run_plan(clock(hour=10, minute=21), delivered=self.baseline())
        self.assertEqual(result["entries"], [])
        result = self.run_plan(clock(hour=10, minute=22), delivered=self.baseline())
        self.assertEqual(result["timeframes"], ["15m"])
        self.assertEqual(result["entries"][0]["target_close"], clock(hour=10, minute=15).isoformat())

    def test_18_minute_delay_keeps_due_45m_and_selects_only_latest_15m(self):
        result = self.run_plan(clock(hour=11, minute=55), delivered=self.baseline())
        current = entries(result)
        self.assertEqual(result["timeframes"], ["15m", "30m", "45m", "1h"])
        self.assertEqual(current["45m"]["target_close"], clock(hour=11, minute=30).isoformat())
        self.assertEqual(current["45m"]["lateness_seconds"], 18 * 60)
        self.assertEqual(current["15m"]["target_close"], clock(hour=11, minute=45).isoformat())
        self.assertEqual(current["15m"]["missed_slot_count"], 6)
        self.assertEqual(len([e for e in result["entries"] if e["timeframe"] == "15m"]), 1)

    def test_nominal_hour_two_and_four_hour_dispatches(self):
        for hour, expected in [(11, {"15m", "30m", "45m", "1h"}),
                               (12, {"15m", "30m", "45m", "1h", "2h"}),
                               (14, {"15m", "30m", "45m", "1h", "2h", "4h"})]:
            with self.subTest(hour=hour):
                found = self.run_plan(clock(hour=hour), delivered=self.baseline())
                self.assertEqual(set(found["timeframes"]), expected)
                self.assertTrue(all(item["target_close"] <= clock(hour=hour).isoformat()
                                    for item in found["entries"]))

    def test_acknowledged_slots_are_not_repeated_and_only_newest_is_sent(self):
        initial = self.run_plan(clock(hour=11), delivered=self.baseline())
        ledger = {**self.baseline(), **{tf: acknowledged(item)
                                      for tf, item in entries(initial).items()}}
        self.assertEqual(self.run_plan(clock(hour=11, minute=12), delivered=ledger)["entries"], [])
        delayed = entries(self.run_plan(clock(hour=12, minute=22), delivered=ledger))
        self.assertEqual(delayed["15m"]["target_close"], clock(hour=12, minute=15).isoformat())
        self.assertEqual(delayed["15m"]["missed_slot_count"], 4)

    def test_final_pass_and_afterhours_preserve_same_slot_identity(self):
        early = entries(self.run_plan(clock(hour=18, minute=29), delivered=self.baseline()))
        self.assertNotIn("1d", early)
        self.assertEqual(early["15m"]["target_close"], clock(hour=17, minute=45).isoformat())
        final = self.run_plan(clock(hour=18, minute=30), delivered=self.baseline())
        self.assertEqual(tuple(final["timeframes"]), SUPPORTED_TIMEFRAMES)
        for entry in entries(final).values():
            expected = clock(hour=18, minute=0)
            self.assertEqual(entry["target_close"], expected.isoformat())
        ledger = {tf: acknowledged(item) for tf, item in entries(final).items()}
        self.assertEqual(self.run_plan(clock(hour=23, minute=40), delivered=ledger)["entries"], [])

    def test_45m_closing_auction_pass_follows_acknowledged_1730_slot(self):
        old = entries(self.run_plan(clock(hour=17, minute=52), delivered=self.baseline()))["45m"]
        self.assertEqual(old["target_close"], clock(hour=17, minute=30).isoformat())
        state = acknowledged(old)
        self.assertIs(validate_delivery_state(state), state)
        ledger = {**self.baseline(), "45m": state}
        self.assertNotIn("45m", entries(self.run_plan(clock(hour=18, minute=29), delivered=ledger)))
        final = entries(self.run_plan(clock(hour=18, minute=30), delivered=ledger))["45m"]
        self.assertEqual(final["target_close"], clock(hour=18, minute=0).isoformat())
        self.assertEqual(validate_delivery_state(acknowledged(final))["receipt"]["status"], "sent")

    def test_weekend_holiday_and_nextday_premarket_use_previous_real_session(self):
        for now in [clock(day=17, hour=12), clock(day=19, hour=9)]:
            result = self.run_plan(now)
            self.assertEqual(result["session"], "2026-10-16")
            self.assertTrue(all(item["session"] == "2026-10-16" for item in result["entries"]))
        holiday = plan(clock(), calendar=Calendar(holidays=[date(2026, 10, 20)]))
        self.assertEqual(holiday["session"], "2026-10-19")

    def test_first_run_reports_missed_slots_for_selected_session_only(self):
        item = entries(self.run_plan(clock(hour=12, minute=22)))["15m"]
        self.assertEqual(item["missed_slot_count"], 8)

    def test_shortened_session_is_explicitly_unsupported_not_empty_success(self):
        result = plan(clock(hour=11), calendar=Calendar(half_days=[date(2026, 10, 20)]))
        self.assertEqual(result["status"], "unsupported_partial_session")
        self.assertEqual(result["entries"], [])
        self.assertIn("12:30", result["unsupported"]["close"])

    def test_manual_all_is_seven_previews_never_a_delivery_watermark(self):
        result = self.run_plan(clock(hour=10, minute=5), force_all=True)
        self.assertEqual(tuple(result["timeframes"]), SUPPORTED_TIMEFRAMES)
        self.assertTrue(all(item["manual_only"] is True for item in result["entries"]))
        for item in result["entries"]:
            with self.assertRaisesRegex(ValueError, "manual_preview"):
                validate_delivery_state(acknowledged(item))

    def test_naive_clock_and_future_watermark_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone_aware"):
            self.run_plan(datetime(2026, 10, 20, 11, 7))
        with self.assertRaisesRegex(ValueError, "future"):
            self.run_plan(clock(day=19, hour=11), delivered=self.baseline())

    def test_utc_clock_has_same_slots_as_istanbul(self):
        utc = datetime.fromisoformat("2026-10-20T08:07:00+00:00")
        self.assertEqual(self.run_plan(utc), self.run_plan(clock()))


class DeliveryStateTests(unittest.TestCase):
    def setUp(self):
        self.state = acknowledged(plan(clock(), calendar=Calendar())["entries"][0])

    def test_exact_three_ack_receipt_is_accepted(self):
        self.assertIs(validate_delivery_state(self.state), self.state)

    def test_invalid_identity_or_missing_ack_cannot_suppress_delivery(self):
        corruptions = [
            lambda s: s.update(schema="other"),
            lambda s: s.update(sent=False),
            lambda s: s.update(session="2026-10-19"),
            lambda s: s.update(slot_key="arbitrary"),
            lambda s: s.update(scheduled_at="2026-10-20T11:07:00"),
            lambda s: s.update(packet_sha256="bad"),
            lambda s: s["receipt"].update(chat_id=-123),
            lambda s: s["receipt"].update(topic_id=28328),
            lambda s: s["receipt"].update(packet_sha256="b" * 64),
            lambda s: s["receipt"].update(status="partial"),
            lambda s: s["receipt"]["acknowledged"].pop("csv"),
            lambda s: s["receipt"]["acknowledged"].update(photo=True),
            lambda s: s["receipt"]["acknowledged"].update(csv=0),
        ]
        for mutation in corruptions:
            with self.subTest(mutation=mutation):
                state = copy.deepcopy(self.state)
                mutation(state)
                with self.assertRaises(ValueError):
                    validate_delivery_state(state)

    def test_ledger_directory_missing_is_bootstrap_but_malformed_is_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(load_delivered(root / "not-restored"), {})
            target = root / "15m.json"
            target.write_text(json.dumps(self.state), encoding="utf-8")
            self.assertEqual(load_delivered(root), {"15m": self.state})
            target.write_text("broken", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_delivered(root)

    def test_cli_exports_json_matrix_and_plan_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "github-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), patch(
                "scripts.atc_snapshot_schedule._XistCalendar", return_value=Calendar(),
            ), patch("builtins.print"):
                result = main(["--ledger-dir", str(root / "ledger"), "--now",
                               clock().isoformat(), "--output", str(root / "plan.json")])
            fields = dict(line.split("=", 1) for line in output.read_text().splitlines())
            self.assertEqual(json.loads(fields["matrix"]), result["entries"])
            self.assertEqual(fields["plan_status"], "ready")
            self.assertEqual(json.loads((root / "plan.json").read_text()), result)


if __name__ == "__main__":
    unittest.main()
