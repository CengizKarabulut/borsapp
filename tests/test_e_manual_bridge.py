from __future__ import annotations

import builtins
import importlib.util
import sys
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.atc_pivot_ladder import LEVEL_FIELDS, traditional_pivot_ladder
from scripts.atc_support_resistance import build_support_resistance

_SCRIPT = Path(__file__).parents[1] / "scripts/e_manual_bridge.py"
_SPEC = importlib.util.spec_from_file_location("manual_bridge_under_test", _SCRIPT)
bridge = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bridge)
START = datetime(2026, 1, 1, tzinfo=UTC)
ROOT = Path("E:/Borsapp-Manual")


def fixture(*, partial=False, count=1):
    lows = [95, 94, 93, 80, 92, 93, 94, 95, 85, 94, 95, 96, 97]
    bars = tuple(SimpleNamespace(
        open_time=START + timedelta(days=i),
        close_time=START + timedelta(days=i + 1),
        open=100.0, high=110.0, low=float(low), close=100.0,
    ) for i, low in enumerate(lows))
    frame = SimpleNamespace(
        bars=bars, source="fixture-provider", symbol_at_snapshot="ASELS",
        snapshot_id="exact-snapshot", series_revision=2,
        timeframe=SimpleNamespace(value="1d"), price_basis=SimpleNamespace(value="split_adjusted"),
        is_partial=partial, quality="preliminary" if partial else "complete",
        through_bar_time=bars[-1].close_time,
    )
    observed = {
        "symbol": "ASELS", "snapshot_id": frame.snapshot_id,
        "source": frame.source, "price_basis": frame.price_basis.value,
        "observed_at": (bars[-1].close_time + timedelta(hours=1)).isoformat(),
        "bar_open": bars[-1].open_time.isoformat(),
        "bar_end": bars[-1].close_time.isoformat(), "partial": partial,
        "frame_archive": {"status": "archived", "snapshot_id": frame.snapshot_id,
                          "sha256": "a" * 64, "path": "frames/" + "a" * 64 + ".json.gz"},
    }
    plan = {
        "status": "calibrated_reference", "scenarios": [{
            "side": "short", "entry": 100.0, "stop": 105.0,
            "tp1": 95.0, "tp2": 90.0, "tp3": 85.0,
            "profile_id": "verified-profile", "stop_basis": "validated_fixed_atr_multiplier",
        }],
    }
    item = {
        "symbol": "ASELS", "snapshot_id": frame.snapshot_id, "timeframe": "1d",
        "bar_time": observed["bar_end"], "bar_open": observed["bar_open"],
        "observed_at": observed["observed_at"], "preliminary": partial, "bar_confirmed": not partial,
        "direction": "bearish", "plan": plan,
        "metrics": {"trade_plan": deepcopy(plan), "evidence": [1, 2]},
        "exit_calibration": {"status": "active", "applied": True, "profile_id": "verified-profile"},
    }
    details = [dict(deepcopy(item), scanner="rule-" + str(i + 1)) for i in range(count)]
    result = {
        "market": "bist", "timeframe": "1d", "details": details,
        "findings": deepcopy(details), "observations": [observed],
        "coverage": {"expected": 631, "attempted": 631, "successful": 630, "failed": 1},
        "preliminary": partial, "archive_failures": [],
    }
    job = {"run_id": "1" * 32, "timeframe": "1d"}
    return frame, result, job


def enrich(frame, result, job, *, reader=None):
    reader = reader if reader is not None else Mock(return_value=frame)
    output = bridge.enrich_result(result, job, ROOT, archive_reader=reader,
                                  support_builder=build_support_resistance,
                                  pivot_builder=traditional_pivot_ladder)
    return output, reader


class EManualBridgeTests(unittest.TestCase):
    def test_real_context_does_not_mutate_plans_calibration_metrics_or_coverage(self):
        frame, result, job = fixture()
        original = deepcopy(result)
        output, reader = enrich(frame, result, job)
        self.assertEqual(result, original)
        self.assertEqual(output["coverage"], original["coverage"])
        for key in ("plan", "metrics", "exit_calibration"):
            self.assertEqual(output["details"][0][key], original["details"][0][key])
        context = output["details"][0]["support_resistance"]
        self.assertEqual(context["status"], "ready")
        self.assertEqual(context["snapshot_id"], frame.snapshot_id)
        self.assertEqual(context["as_of"], result["observations"][0]["observed_at"])
        self.assertFalse(context["algorithm"]["changes_stop_tp"])
        reader.assert_called_once_with(ROOT, job["run_id"], result["observations"][0]["frame_archive"])
        self.assertEqual(output["support_resistance_context"]["snapshots_read"], 1)
        ladder = output["details"][0]["pivot_ladder"]
        expected = traditional_pivot_ladder(frame.bars[-1].high, frame.bars[-1].low, frame.bars[-1].close)
        self.assertEqual({key: ladder[key] for key in LEVEL_FIELDS},
                         {key: expected[key] for key in LEVEL_FIELDS})
        self.assertEqual(ladder["formula_method"], "traditional")
        self.assertEqual(ladder["reference_basis"], "last_completed_timeframe_bar")
        self.assertEqual(ladder["reference_bar_end"], frame.bars[-1].close_time.isoformat())
        self.assertEqual(ladder["source"], frame.source)
        self.assertEqual(ladder["snapshot_id"], frame.snapshot_id)

    def test_all_eighteen_findings_share_one_verified_archive_read_and_calculation(self):
        frame, result, job = fixture(count=18)
        reader = Mock(return_value=frame)
        builder = Mock(side_effect=build_support_resistance)
        pivot_builder = Mock(side_effect=traditional_pivot_ladder)
        output = bridge.enrich_result(result, job, ROOT, archive_reader=reader, support_builder=builder,
                                     pivot_builder=pivot_builder)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(builder.call_count, 1)
        self.assertEqual(pivot_builder.call_count, 1)
        self.assertEqual(len(output["details"]), 18)
        self.assertTrue(all(row["support_resistance"]["status"] == "ready" for row in output["details"]))
        self.assertTrue(all(row["pivot_ladder"]["status"] == "ready" for row in output["details"]))

    def test_each_detail_identity_must_match_even_after_a_valid_cached_finding(self):
        changes = {
            "timeframe": "4h", "bar_time": START.isoformat(),
            "observed_at": START.isoformat(), "bar_open": START.isoformat(),
            "preliminary": True, "bar_confirmed": False,
        }
        for field, invalid in changes.items():
            for bad_index in (0, 1):
                with self.subTest(field=field, bad_index=bad_index):
                    frame, result, job = fixture(count=2)
                    result["details"][bad_index][field] = invalid
                    output, _ = enrich(frame, result, job)
                    self.assertNotEqual(output["details"][bad_index]["support_resistance"]["status"], "ready")
                    self.assertEqual(output["details"][1 - bad_index]["support_resistance"]["status"], "ready")
                    self.assertNotEqual(output["details"][bad_index]["pivot_ladder"]["status"], "ready")
                    self.assertEqual(output["details"][1 - bad_index]["pivot_ladder"]["status"], "ready")

    def test_archive_frame_observation_and_detail_identity_mismatches_fail_closed(self):
        cases = [
            ("observation", "source", "different-feed"),
            ("observation", "price_basis", "raw"),
            ("observation", "bar_end", START.isoformat()),
            ("observation", "bar_open", START.isoformat()),
            ("observation", "partial", True),
            ("observation", "observed_at", START.isoformat()),
            ("detail", "snapshot_id", "different-snapshot"),
            ("detail", "symbol", "THYAO"),
            ("frame", "snapshot_id", "modified-snapshot"),
            ("frame", "symbol_at_snapshot", "THYAO"),
            ("frame", "source", "wrong-feed"),
        ]
        for kind, field, invalid in cases:
            with self.subTest(kind=kind, field=field):
                frame, result, job = fixture()
                if kind == "frame":
                    setattr(frame, field, invalid)
                else:
                    target = result["observations"][0] if kind == "observation" else result["details"][0]
                    target[field] = invalid
                output, _ = enrich(frame, result, job)
                self.assertEqual(output["details"][0]["support_resistance"]["status"], "unavailable_data_quality")
                self.assertEqual(output["details"][0]["pivot_ladder"]["status"], "unavailable_data_quality")

    def test_duplicate_observations_are_ambiguous_and_never_read_archive(self):
        frame, result, job = fixture()
        result["observations"].append(deepcopy(result["observations"][0]))
        output, reader = enrich(frame, result, job)
        reader.assert_not_called()
        self.assertEqual(output["details"][0]["support_resistance"]["status"], "unavailable_data_quality")
        self.assertEqual(output["details"][0]["pivot_ladder"]["status"], "unavailable_data_quality")

    def test_archive_hash_read_failure_adds_only_unavailable_context(self):
        frame, result, job = fixture()
        original = deepcopy(result)
        reader = Mock(side_effect=ValueError("frame_archive_hash_mismatch"))
        output, _ = enrich(frame, result, job, reader=reader)
        self.assertEqual(result, original)
        self.assertEqual(output["coverage"], original["coverage"])
        self.assertEqual(output["details"][0]["plan"], original["details"][0]["plan"])
        self.assertEqual(output["details"][0]["support_resistance"]["status"], "unavailable_data_quality")
        self.assertEqual(output["details"][0]["pivot_ladder"]["status"], "unavailable_data_quality")

    def test_asof_requires_an_aware_timestamp_in_the_actual_archive_context(self):
        frame, result, job = fixture()
        naive = "2026-01-14T01:00:00"
        result["observations"][0]["observed_at"] = naive
        result["details"][0]["observed_at"] = naive
        output, _ = enrich(frame, result, job)
        self.assertEqual(output["details"][0]["support_resistance"]["status"], "unavailable_data_quality")

    def test_partial_extreme_current_candle_cannot_change_confirmed_levels(self):
        frame, result, job = fixture(partial=True)
        expected, _ = enrich(frame, result, job)
        frame.bars[-1].low, frame.bars[-1].high, frame.bars[-1].close = 0.001, 100000.0, 90000.0
        actual, _ = enrich(frame, result, job)
        before = expected["details"][0]["support_resistance"]
        after = actual["details"][0]["support_resistance"]
        for key in ("supports", "resistances", "reference_price", "last_closed_bar_time"):
            self.assertEqual(before[key], after[key])
        self.assertEqual(after["excluded_open_or_future_bars"], 1)
        self.assertEqual(expected["details"][0]["pivot_ladder"], actual["details"][0]["pivot_ladder"])
        self.assertEqual(actual["details"][0]["pivot_ladder"]["reference_bar_end"],
                         frame.bars[-2].close_time.isoformat())

    def test_one_actual_closed_bar_is_enough_for_formula_ladder_not_confirmed_structure(self):
        frame, result, job = fixture()
        frame.bars = (frame.bars[-1],)
        output, _ = enrich(frame, result, job)
        self.assertEqual(output["details"][0]["support_resistance"]["status"], "insufficient_history")
        self.assertEqual(output["details"][0]["pivot_ladder"]["status"], "ready")

    def test_only_partial_bar_cannot_be_used_as_closed_pivot_reference(self):
        frame, result, job = fixture(partial=True)
        frame.bars = (frame.bars[-1],)
        output, _ = enrich(frame, result, job)
        ladder = output["details"][0]["pivot_ladder"]
        self.assertEqual(ladder["status"], "unavailable_closed_reference")
        self.assertIsNone(ladder["reference_bar_end"])
        self.assertEqual(ladder["excluded_open_or_future_bars"], 1)
        self.assertTrue(all(ladder[key] is None for key in LEVEL_FIELDS))

    def test_future_bar_is_excluded_even_without_partial_marker(self):
        frame, result, job = fixture()
        as_of = (frame.bars[-1].open_time + timedelta(hours=1)).isoformat()
        result["observations"][0]["observed_at"] = as_of
        result["details"][0]["observed_at"] = as_of
        output, _ = enrich(frame, result, job)
        ladder = output["details"][0]["pivot_ladder"]
        self.assertEqual(ladder["status"], "ready")
        self.assertEqual(ladder["reference_bar_end"], frame.bars[-2].close_time.isoformat())
        self.assertEqual(ladder["excluded_open_or_future_bars"], 1)

    def test_intraday_reference_is_labelled_with_its_actual_timeframe(self):
        frame, result, job = fixture()
        frame.timeframe.value = job["timeframe"] = result["details"][0]["timeframe"] = "1h"
        for index, bar in enumerate(frame.bars):
            bar.open_time, bar.close_time = START + timedelta(hours=index), START + timedelta(hours=index + 1)
        frame.through_bar_time = frame.bars[-1].close_time
        observed = result["observations"][0]
        observed.update(bar_open=frame.bars[-1].open_time.isoformat(),
                        bar_end=frame.bars[-1].close_time.isoformat(),
                        observed_at=(frame.bars[-1].close_time + timedelta(minutes=1)).isoformat())
        result["details"][0].update(bar_open=observed["bar_open"], bar_time=observed["bar_end"],
                                    observed_at=observed["observed_at"])
        output, _ = enrich(frame, result, job)
        item = output["details"][0]
        self.assertEqual(item["pivot_ladder"]["timeframe"], "1h")
        text = bridge.pivot_context_line(item)
        self.assertIn("1h · son kapalı mum", text)
        self.assertNotIn("günlük", text)
        self.assertIn("S3", text)
        self.assertIn("R3", text)

    def test_flat_and_invalid_formula_prices_are_explained_without_padding(self):
        for values, expected_status, explanation in (
            ((100.0, 100.0, 100.0), "flat_session_coincident_levels", "seviyeler çakışır"),
            ((100.0, 1.0, 1.0), "partial_nonpositive_levels", "uygulanamaz fiyat alanları boş"),
        ):
            with self.subTest(status=expected_status):
                frame, result, job = fixture()
                reference = frame.bars[-1]
                reference.high, reference.low, reference.close = values
                reference.open = reference.close
                output, _ = enrich(frame, result, job)
                item = output["details"][0]
                self.assertEqual(item["pivot_ladder"]["status"], expected_status)
                text = bridge.pivot_context_line(item)
                self.assertIn(explanation, text)
                if expected_status == "partial_nonpositive_levels":
                    self.assertIsNone(item["pivot_ladder"]["S1"])
                    self.assertIn("S1 —", text)
                    self.assertNotIn("S1 -", text)

    def test_nearest_complete_short_scenario_and_context_are_formatted_without_remapping(self):
        _, result, _ = fixture()
        item = result["details"][0]
        farther = dict(item["plan"]["scenarios"][0], stop=110.0, tp1=90.0, tp2=80.0, tp3=70.0)
        item["plan"]["scenarios"].insert(0, farther)
        item["support_resistance"] = {"status": "ready", "supports": [{"price": 80.0}],
                                      "resistances": [{"price": 110.0}]}
        module = SimpleNamespace(_plan_line=lambda row: "fallback")
        with bridge.presentation_adapter(module):
            text = module._plan_line(item)
        self.assertIn("Stop 105.00 · TP1 95.00 · TP2 90.00 · TP3 85.00", text)
        self.assertIn("Kalibre referans", text)
        self.assertIn("D/R (kapanmış mum): Destek 80 · Direnç 110", text)
        self.assertNotIn("Stop 110.00", text)

    def test_unavailable_short_plan_has_explicit_message_and_never_displays_negative_diagnostic(self):
        item = {"direction": "bearish", "plan": {
            "status": "unavailable", "reason": "nonpositive_level", "scenarios": [],
            "display_levels": {"entry": 1.0, "stop": 10.0, "tp1": -8.0, "tp2": -17.0, "tp3": -26.0},
        }}
        text = bridge.format_plan_line(item, lambda row: "")
        self.assertIn("uygulanabilir plan yok", text)
        self.assertNotIn("-8", text)

    def test_presentation_context_restores_both_hooks_after_exception(self):
        def original_line(row):
            return "original"

        def original_run(*args, **kwargs):
            return "run"
        module = SimpleNamespace(_plan_line=original_line, run_once=original_run)
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            with bridge.presentation_adapter(module, root=ROOT):
                self.assertIsNot(module._plan_line, original_line)
                self.assertIsNot(module.run_once, original_run)
                raise RuntimeError("cancelled")
        self.assertIs(module._plan_line, original_line)
        self.assertIs(module.run_once, original_run)

    def test_preview_bypasses_engine_import_and_preserves_original_options(self):
        original_run = Mock(return_value={"status": "preview"})
        module = SimpleNamespace(_plan_line=lambda row: "", run_once=original_run)
        imported = builtins.__import__
        def guarded(name, *args, **kwargs):
            if name == "market_intelligence.native.engine":
                raise AssertionError("preview must not import a scan engine")
            return imported(name, *args, **kwargs)
        with bridge.presentation_adapter(module, root=ROOT), patch("builtins.__import__", side_effect=guarded):
            output = module.run_once(ROOT, "selection", preview=True)
        self.assertEqual(output, {"status": "preview"})
        original_run.assert_called_once_with(ROOT, "selection", preview=True)

    def test_nonpreview_hook_enriches_only_the_return_of_the_existing_executor(self):
        frame, result, job = fixture()
        progress = object()
        executor = Mock(return_value=result)
        enriched = {**result, "support_resistance_context": {"ready": 1}}
        enrich_result = Mock(return_value=enriched)
        def original_run(root, selection, **kwargs):
            self.assertEqual(root, ROOT)
            self.assertEqual(selection, "selected-scanners")
            self.assertEqual(kwargs["artifact_factory"], "existing-artifacts")
            return kwargs["executor"](job, root, progress=progress)
        def original_line(row):
            return "existing-plan"
        module = SimpleNamespace(_plan_line=original_line, run_once=original_run)
        engine = SimpleNamespace(execute_scan=Mock(side_effect=AssertionError("injected executor expected")))
        with patch.dict(sys.modules, {"market_intelligence.native.engine": engine}), \
                patch.object(bridge, "enrich_result", enrich_result), \
                bridge.presentation_adapter(module, root=ROOT):
            output = module.run_once(ROOT, "selected-scanners", executor=executor,
                                     artifact_factory="existing-artifacts")
        self.assertIs(output, enriched)
        executor.assert_called_once_with(job, ROOT, progress=progress)
        enrich_result.assert_called_once_with(result, job, ROOT)
        engine.execute_scan.assert_not_called()
        self.assertIs(module.run_once, original_run)
        self.assertIs(module._plan_line, original_line)


if __name__ == "__main__":
    unittest.main()
