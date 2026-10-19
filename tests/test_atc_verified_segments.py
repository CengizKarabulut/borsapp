from __future__ import annotations

import unittest
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

from scripts.atc_verified_segments import (
    BasisVerification,
    partition_observed_history,
    prepare_verified_segments,
    unverified_dates,
)

SOURCE = "a" * 64
EVIDENCE = "b" * 64
SNAPSHOT = "c" * 64
AS_OF = datetime(2026, 1, 20, 18, tzinfo=UTC)


def row(day, hour=7):
    return {"timestamp": f"2026-01-{day:02d}T{hour:02d}:00:00+00:00",
            "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.0, "volume": 100.0}


def minute_rows(day, count=60):
    opened = datetime.fromisoformat(row(day)["timestamp"])
    return tuple({**row(day), "timestamp": (opened+timedelta(minutes=i)).isoformat()}
                 for i in range(count))


@dataclass(frozen=True)
class Bar:
    open_time: datetime
    close_time: datetime


@dataclass(frozen=True)
class Frame:
    bars: tuple[Bar, ...]
    snapshot_id: str = SNAPSHOT
    price_basis: str = "split_adjusted"
    quality: str = "complete"
    is_partial: bool = False


def verification(**overrides):
    return replace(BasisVerification(
        SOURCE, EVIDENCE, "independent_source_reconciliation", verified=True), **overrides)


def fixture_builder(count=60, **frame_overrides):
    calls = []

    def prepare(rows, *, as_of, segment_id, reset_state):
        calls.append({"rows": rows, "as_of": as_of, "segment_id": segment_id,
                      "reset_state": reset_state})
        opened = datetime.fromisoformat(rows[0]["timestamp"])
        # Minute bars are a bounded contract fixture, not fabricated market data.
        bars = tuple(Bar(opened + timedelta(minutes=i), opened + timedelta(minutes=i+1))
                     for i in range(count))
        return Frame(bars, **frame_overrides)

    return prepare, calls


class HistoryPartitionTests(unittest.TestCase):
    def test_gap_and_fully_absent_day_remain_separate(self):
        rows = (row(1), row(2), row(3), row(5), row(6))
        partitions = partition_observed_history(
            rows, ("2026-01-03", "2026-01-04"), as_of=AS_OF)
        self.assertEqual([span["rows"] for span in partitions],
                         [(rows[0], rows[1]), (rows[3], rows[4])])
        self.assertEqual(partitions[0]["before_excluded_date"], "2026-01-03")
        self.assertEqual(partitions[1]["after_excluded_date"], "2026-01-04")
        self.assertEqual(rows[2], row(3))
        partitions[0]["rows"][0]["close"] = 10.5
        self.assertEqual(rows[0]["close"], 10.0)

    def test_calendar_exclusion_must_be_explicit(self):
        coverage = {"missing_dates": ["2026-01-02"],
                    "reconciliation_failures": [
                        {"date": "2026-01-04", "code": "missing_hourly_day"},
                        {"date": "2026-01-05", "code": "daily_volume_mismatch"}]}
        self.assertEqual(unverified_dates(coverage), ("2026-01-02", "2026-01-04"))
        self.assertEqual(unverified_dates(coverage, documented_excluded_dates=("2026-01-02",)),
                         ("2026-01-04",))

    def test_timezone_and_causality(self):
        rows = ({**row(1), "timestamp": "2026-01-01T22:00:00+00:00"}, row(2))
        self.assertEqual(partition_observed_history(rows, ("2026-01-02",), as_of=AS_OF), ())
        with self.assertRaisesRegex(ValueError, "future_source"):
            partition_observed_history((row(2),), (), as_of=datetime(2026, 1, 1, tzinfo=UTC))

    def test_invalid_source_rejected(self):
        for rows, message in [
            ((row(2), row(1)), "strictly_ordered"),
            ((row(1), row(1)), "strictly_ordered"),
            (({**row(1), "timestamp": "2026-01-01T10:00:00"},), "aware_timestamp"),
            (({**row(1), "extra": {}},), "flat_source"),
        ]:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                partition_observed_history(rows, (), as_of=AS_OF)
        with self.assertRaises(ValueError):
            partition_observed_history(({**row(1), "close": float("nan")},), (), as_of=AS_OF)

    def test_selection_fingerprint_changes_with_boundaries_and_prices(self):
        first = partition_observed_history((row(1), row(2)), (), as_of=AS_OF)[0]
        changed = partition_observed_history((row(1), {**row(2), "close": 10.5}), (), as_of=AS_OF)[0]
        bounded = partition_observed_history((row(1), row(2)), ("2026-01-03",), as_of=AS_OF)[0]
        self.assertNotEqual(first["segment_id"], changed["segment_id"])
        self.assertNotEqual(first["segment_id"], bounded["segment_id"])
        self.assertEqual(first["synthetic_rows_created"], 0)


class VerifiedPreparationTests(unittest.TestCase):
    def prepare(self, builder, **overrides):
        arguments = {"source_sha256": SOURCE, "as_of": AS_OF,
                     "prepare_frame": builder, "basis_verification": verification(),
                     "reset_each_segment": True}
        arguments.update(overrides)
        return prepare_verified_segments(minute_rows(1)+minute_rows(3),
                                         ("2026-01-02",), **arguments)

    def test_unverified_or_wrong_source_blocks_callback(self):
        for evidence in (None, {"adjustment": "splits"}, verification(verified=False),
                         verification(source_sha256="d"*64),
                         verification(price_basis="unadjusted"),
                         verification(evidence_sha256="not-a-receipt"),
                         verification(verification_method="provider_label_only")):
            builder, calls = fixture_builder()
            results = self.prepare(builder, basis_verification=evidence)
            self.assertFalse(calls)
            self.assertTrue(all(result["frame"] is None for result in results))
            self.assertTrue(all(result["metadata"]["status"] == "blocked_unverified_price_basis"
                                for result in results))

    def test_missing_reset_or_carried_positions_block_callback(self):
        for policy in ({"reset_each_segment": False}, {"carry_positions": True},
                       {"carry_positions": None}):
            builder, calls = fixture_builder()
            results = self.prepare(builder, **policy)
            self.assertFalse(calls)
            self.assertTrue(all(result["metadata"]["status"] == "blocked_state_reset_contract"
                                for result in results))

    def test_each_span_gets_fresh_context_and_new_derived_frame(self):
        builder, calls = fixture_builder()
        results = self.prepare(builder)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call["reset_state"] is True for call in calls))
        self.assertNotEqual(calls[0]["segment_id"], calls[1]["segment_id"])
        self.assertEqual(calls[0]["rows"], minute_rows(1))
        self.assertEqual(calls[1]["rows"], minute_rows(3))
        for result in results:
            metadata, frame = result["metadata"], result["frame"]
            self.assertTrue(metadata["eligible_for_research"])
            self.assertFalse(metadata["profile_activation_allowed"])
            self.assertEqual(metadata["basis_evidence_sha256"], EVIDENCE)
            self.assertEqual(frame.snapshot_id, metadata["derived_snapshot_id"])
            self.assertNotEqual(frame.snapshot_id, SNAPSHOT)

    def test_short_segments_do_not_weaken_minimum(self):
        builder, _ = fixture_builder(count=59)
        results = self.prepare(builder)
        self.assertTrue(all(result["frame"] is None for result in results))
        self.assertTrue(all(result["metadata"]["status"] == "insufficient_segment_history"
                            for result in results))
        with self.assertRaisesRegex(ValueError, "cannot_weaken"):
            self.prepare(builder, minimum_closed_bars=59)

    def test_future_partial_or_wrong_basis_frame_rejected(self):
        for overrides in ({"price_basis": "unadjusted"}, {"quality": "partial"},
                          {"is_partial": True}):
            builder, _ = fixture_builder(**overrides)
            with self.subTest(overrides=overrides), self.assertRaisesRegex(ValueError, "basis_or_quality"):
                self.prepare(builder)
        future = Frame((Bar(AS_OF, AS_OF+timedelta(hours=1)),))
        with self.assertRaisesRegex(ValueError, "not_closed"):
            self.prepare(lambda *args, **kwargs: future)

    def test_prepared_frame_cannot_reintroduce_omitted_date(self):
        bad = Frame((Bar(datetime(2026, 1, 2, 7, tzinfo=UTC),
                         datetime(2026, 1, 2, 8, tzinfo=UTC)),))
        with self.assertRaisesRegex(ValueError, "outside_selected_span"):
            self.prepare(lambda *args, **kwargs: bad)

    def test_individually_ordered_bars_cannot_overlap(self):
        opened = datetime.fromisoformat(row(1)["timestamp"])
        overlapping = Frame(tuple(Bar(opened + timedelta(minutes=index),
                                      opened + timedelta(minutes=index + 2))
                                  for index in range(60)))
        with self.assertRaisesRegex(ValueError, "overlap_rejected"):
            self.prepare(lambda *args, **kwargs: overlapping)

    def test_builder_cannot_mutate_selected_rows_after_fingerprinting(self):
        builder, _ = fixture_builder()

        def mutate(rows, **kwargs):
            rows[0]["close"] = 9.5
            return builder(rows, **kwargs)

        with self.assertRaisesRegex(ValueError, "changed_source_rows"):
            self.prepare(mutate)

    def test_builder_cannot_invent_additional_bar_count(self):
        builder, _ = fixture_builder(count=61)
        with self.assertRaisesRegex(ValueError, "more_bars_than_observations"):
            self.prepare(builder)


if __name__ == "__main__":
    unittest.main()
