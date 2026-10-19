from __future__ import annotations

import copy
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from scripts.collect_e_adjusted_history import (
    CAPTURE_CONTRACT,
    CAPTURE_METHOD,
    CAPTURE_SOURCE,
    EXPECTED_PROVENANCE,
    SDK_VERSION,
    VERSION,
    collect_series,
    collection_contract,
    load_installed_runtime,
    validate_capture_seam,
    validate_store_namespace,
)


def attestation():
    return {"version": VERSION, "feed_contract": copy.deepcopy(EXPECTED_PROVENANCE),
            "capture_source": CAPTURE_SOURCE, "analysis_enabled": False,
            "activation_enabled": False}


def success(symbol="ASELS", interval="1d", *, reused=False):
    return {"symbol": symbol, "interval": interval, "status": "completed",
            "reference": {"source": CAPTURE_SOURCE, "row_count": 600}, "reused": reused}


class FakeStore:
    def __init__(self, responses=None, *, manifest=None):
        self.responses = list(responses or [])
        self.calls = []
        self.manifest = manifest or {"histories": [], "requests": {}}

    def capture(self, symbol, interval, fetcher, **kwargs):
        self.calls.append((symbol, interval, kwargs))
        if self.responses:
            result = self.responses.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        return success(symbol, interval)


def run_fake(store, *, symbols=("ASELS", "HRKET"), **overrides):
    saved = []
    arguments = {"symbols": symbols, "fetcher": lambda *args: None,
                 "contract": collection_contract(symbols, attestation()),
                 "persist": lambda state: saved.append(copy.deepcopy(state)),
                 "should_stop": lambda: False,
                 "now": lambda: datetime(2026, 10, 19, tzinfo=UTC)}
    arguments.update(overrides)
    return collect_series(store, **arguments), saved


class CorrectedCaptureLoopTests(unittest.TestCase):
    def test_sequential_full_series_and_checkpoints_no_analysis(self):
        store = FakeStore()
        state, saved = run_fake(store)
        self.assertEqual([(s, i) for s, i, _ in store.calls],
                         [("ASELS", "1d"), ("ASELS", "1h"), ("HRKET", "1d"), ("HRKET", "1h")])
        self.assertTrue(all(call[2] == {"requested_start": "1985-01-01", "vintage": "2026-10-19"}
                            for call in store.calls))
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["completed_series"], 4)
        self.assertEqual(state["remaining_series"], 0)
        self.assertGreaterEqual(len(saved), 9)
        for key in ("research_jobs_started", "profiles_activated", "telegram_messages_sent", "real_orders_sent"):
            self.assertEqual(state[key], 0)

    def test_resume_uses_store_revalidation_same_vintage(self):
        store = FakeStore([success(reused=True), success(interval="1h", reused=True),
                           success("HRKET"), success("HRKET", "1h")])
        state, _ = run_fake(store)
        self.assertEqual(state["reused_series"], 2)
        self.assertEqual(state["completed_series"], 4)
        self.assertEqual(len(store.calls), 4)
        self.assertEqual({kwargs["vintage"] for _, _, kwargs in store.calls}, {"2026-10-19"})

    def test_three_consecutive_failures_stop_no_fourth_request(self):
        failed = {"status": "failed", "code": "history_provider_failed"}
        store = FakeStore([failed, failed, failed, success()])
        state, _ = run_fake(store)
        self.assertEqual(len(store.calls), 3)
        self.assertEqual(state["status"], "incomplete")
        self.assertEqual(state["stop_reason"], "three_consecutive_provider_failures")
        self.assertEqual(state["failed_series"], 3)
        self.assertEqual(state["remaining_series"], 1)

    def test_success_resets_consecutive_failure_counter(self):
        failed = {"status": "failed", "code": "history_provider_failed"}
        store = FakeStore([failed, failed, success("HRKET"), failed])
        state, _ = run_fake(store)
        self.assertEqual(len(store.calls), 4)
        self.assertEqual(state["consecutive_failures"], 1)
        self.assertEqual(state["status"], "incomplete")

    def test_stop_before_account_or_request(self):
        entered = []

        @contextmanager
        def account():
            entered.append(True)
            yield

        store = FakeStore()
        state, _ = run_fake(store, should_stop=lambda: True, account_context=account)
        self.assertFalse(entered)
        self.assertFalse(store.calls)
        self.assertEqual(state["status"], "paused")

    def test_stop_after_first_keeps_completed_checkpoint(self):
        store = FakeStore()
        state, saved = run_fake(store, should_stop=lambda: bool(store.calls))
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["completed_series"], 1)
        self.assertEqual(len(store.calls), 1)
        self.assertEqual(saved[-1]["completed_series"], 1)

    def test_account_failure_records_type_without_secret_text(self):
        @contextmanager
        def account():
            raise RuntimeError("private-session-secret")
            yield

        store = FakeStore()
        state, saved = run_fake(store, account_context=account)
        self.assertFalse(store.calls)
        self.assertEqual(state["failure_code"], "RuntimeError")
        self.assertNotIn("private-session-secret", json.dumps(saved))

    def test_disk_loss_preserves_in_memory_counts_without_error_text(self):
        store = FakeStore([success(), OSError("private-path")])
        state, _ = run_fake(store)
        self.assertEqual(state["status"], "incomplete")
        self.assertEqual(state["failure_code"], "OSError")
        self.assertEqual(state["completed_series"], 1)
        self.assertNotIn("private-path", json.dumps(state))

    def test_summary_io_failure_stops_before_network(self):
        store = FakeStore()

        def failed_write(state):
            raise OSError("private-disk-path")

        state, _ = run_fake(store, persist=failed_write)
        self.assertFalse(store.calls)
        self.assertTrue(state["summary_write_failed"])
        self.assertEqual(state["status"], "incomplete")

    def test_legacy_namespace_rejected_before_persist(self):
        old = FakeStore(manifest={"histories": [{"source": "borsapy-tradingview-0.11.0"}],
                                  "requests": {}})
        with self.assertRaisesRegex(ValueError, "legacy_history"):
            run_fake(old)
        oldkey = FakeStore(manifest={"histories": [], "requests": {"ASELS:1d:vintage-2026-10-15": {}}})
        with self.assertRaisesRegex(ValueError, "legacy_request"):
            validate_store_namespace(oldkey)

    def test_wrong_returned_source_and_modified_contract_fail_closed(self):
        bad = success()
        bad["reference"]["source"] = "nominal-v1"
        state, _ = run_fake(FakeStore([bad]))
        self.assertEqual(state["status"], "incomplete")
        self.assertEqual(state["completed_series"], 0)
        contract = collection_contract(("ASELS",), attestation())
        contract["requested_start"] = "2026-10-01"
        with self.assertRaisesRegex(ValueError, "contract_hash"):
            run_fake(FakeStore(), symbols=("ASELS",), contract=contract)


class CorrectedCaptureSeamTests(unittest.TestCase):
    def modules(self):
        def verify(value):
            return copy.deepcopy(EXPECTED_PROVENANCE) if json.dumps(value, sort_keys=True) == json.dumps(EXPECTED_PROVENANCE, sort_keys=True) else None

        market = SimpleNamespace(_split_history_provenance=lambda: copy.deepcopy(EXPECTED_PROVENANCE),
                                 _verified_split_provenance=verify)
        history = SimpleNamespace(SDK_VERSION=SDK_VERSION, CAPTURE_SOURCE=CAPTURE_SOURCE,
                                  CAPTURE_METHOD=CAPTURE_METHOD, CAPTURE_CONTRACT=CAPTURE_CONTRACT,
                                  _capture_contract=lambda value: verify(value.attrs["atc_price_provenance"]))
        return market, history

    def test_semantic_seam_requires_adjust_true_not_metadata_alone(self):
        market, history = self.modules()
        good = "def _history():\n    kwargs = {'adjust': True, 'auto_adjust': False, 'actions': False}\n"
        self.assertEqual(validate_capture_seam(market, history, source=good), EXPECTED_PROVENANCE)
        for source in (good.replace("'adjust': True", "'adjust': False"),
                       good.replace("'adjust': True", "'adjust': 1")):
            with self.assertRaisesRegex(ValueError, "explicit_adjust_true"):
                validate_capture_seam(market, history, source=source)

    def test_numeric_boolean_and_old_store_contract_rejected(self):
        market, history = self.modules()
        market._verified_split_provenance = lambda value: EXPECTED_PROVENANCE
        with self.assertRaisesRegex(ValueError, "accepts_wrong_contract"):
            validate_capture_seam(market, history, source="pass")
        market, history = self.modules()
        history.CAPTURE_SOURCE = "old-source"
        with self.assertRaisesRegex(ValueError, "history_store_capture_contract"):
            validate_capture_seam(market, history, source="pass")

    def test_file_hash_mismatch_fails_before_imports_or_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            native = root / "src/market_intelligence/native/market_data.py"
            native.parent.mkdir(parents=True)
            native.write_text("old-seam", encoding="utf-8")
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            with self.assertRaisesRegex(ValueError, "capture_file_hash_mismatch"):
                load_installed_runtime(root, expected_identity="a"*64,
                                       expected_market_data="b"*64, expected_history_store="c"*64)
            self.assertEqual(before, sorted(str(path.relative_to(root)) for path in root.rglob("*")))
            self.assertEqual(native.read_text(), "old-seam")


if __name__ == "__main__":
    unittest.main()
