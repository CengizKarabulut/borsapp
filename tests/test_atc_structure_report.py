from __future__ import annotations

import copy
import csv
import io
import json
import math
import shutil
import tempfile
import unittest
from collections import Counter
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from market_intelligence.core.enums import PriceBasis
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.providers import ProviderBar, ProviderFrame, TimestampKind
from scripts import atc_structure_report as report
from scripts.atc_universe_seed import load_pinned

IST = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 19, 17, 20, tzinfo=IST)
PREVIOUS = date(2026, 10, 16)
ENV = {"TELEGRAM_CHAT_ID": str(report.CHAT), "TELEGRAM_TOPIC_REPORTS": "8"}


def sample_bars(count=150, *, previous=PREVIOUS):
    days = []
    day = previous
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    result = []
    for index, day in enumerate(reversed(days)):
        value = 100 + 5 * math.sin(index / 3)
        result.append(ProviderBar(timestamp=datetime.combine(day, datetime.min.time(), IST),
            open=value, high=value + 2, low=value - 2, close=value, volume=1000))
    return tuple(result)


def vendor(bars, *, source="test_vendor", symbol="ASELS"):
    mock = Mock(name="mock_vendor")
    mock.name = source
    mock.fetch.return_value = ProviderFrame(provider=source, provider_symbol=symbol,
        timeframe=Timeframe.D1, timestamp_kind=TimestampKind.OPEN,
        timestamp_timezone="Europe/Istanbul", price_basis=PriceBasis.SPLIT_ADJUSTED,
        bars=tuple(bars), last_bar_is_partial=False)
    return mock


class ClosedReportSourceTests(unittest.TestCase):
    def test_same_bist_aliases_allow_real_secondary_provider_fallback(self):
        for alias in ("BIST:ASELS", "ASELS.IS", "BIST:ASELS.IS"):
            with self.subTest(alias=alias):
                first = vendor(sample_bars(), source="unavailable")
                first.fetch.side_effect = RuntimeError("unavailable")
                backup = vendor(sample_bars(), source="tvdatafeed", symbol=alias)
                row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
                    providers=(first, backup))
                self.assertEqual(row["status"], "fresh_closed_source")
                self.assertEqual(row["symbol"], "ASELS")
                self.assertEqual(row["source"], "tvdatafeed")
                first.fetch.assert_called_once()
                backup.fetch.assert_called_once()

    def test_provider_alias_cannot_change_exchange_or_instrument(self):
        for alias in ("NYSE:ASELS", "NASDAQ:ASELS.IS", "BIST:THYAO", "BIST:BIST:ASELS"):
            with self.subTest(alias=alias):
                row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
                    providers=(vendor(sample_bars(), symbol=alias),))
                self.assertEqual(row["status"], "source_unavailable")

    def test_dated_official_halt_keeps_exact_pre_halt_real_reference_without_fresh_label(self):
        before_halt = date(2026, 10, 19)
        expected = date(2026, 10, 20)
        source = vendor(sample_bars(previous=before_halt), symbol="RALYH")
        row = report.read_structure("RALYH", previous=expected,
            now=datetime(2026, 10, 21, 8, 35, tzinfo=IST), providers=(source,))
        self.assertEqual(row["status"], "official_halt_reference")
        self.assertEqual(row["session"], "2026-10-20")
        self.assertEqual(row["reference_session"], "2026-10-19")
        self.assertEqual(row["market_status"]["source_url"], "https://www.kap.org.tr/tr/Bildirim/1684170")
        self.assertEqual(row["market_status"]["resume_session"], "2026-10-21")
        self.assertEqual(row["reference_ohlc"]["close"], source.fetch.return_value.bars[-1].close)
        self.assertEqual(row["pivot_ladder"]["status"], "ready")

    def test_halt_notice_does_not_authorize_arbitrary_older_data_or_unrelated_symbol(self):
        for symbol, prior in (("RALYH", date(2026, 10, 16)), ("ASELS", date(2026, 10, 19))):
            with self.subTest(symbol=symbol):
                row = report.read_structure(symbol, previous=date(2026, 10, 20),
                    now=datetime(2026, 10, 21, 8, 35, tzinfo=IST),
                    providers=(vendor(sample_bars(previous=prior), symbol=symbol),))
                self.assertEqual(row["status"], "source_unavailable")
                self.assertIsNone(row["reference_session"])

    def test_halt_reference_exception_expires_and_rejects_candles_on_halted_session(self):
        for expected, prior, now in (
            (date(2026, 10, 21), date(2026, 10, 19), datetime(2026, 10, 22, 8, 35, tzinfo=IST)),
            (date(2026, 10, 20), date(2026, 10, 20), datetime(2026, 10, 21, 8, 35, tzinfo=IST)),
        ):
            with self.subTest(expected=expected, prior=prior):
                row = report.read_structure("RALYH", previous=expected, now=now,
                    providers=(vendor(sample_bars(previous=prior), symbol="RALYH"),))
                self.assertEqual(row["status"], "source_unavailable")

    def test_three_formula_levels_exist_independently_of_confirmed_swing_count(self):
        bars = sample_bars()
        row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
            providers=(vendor(bars),))
        ladder = row["pivot_ladder"]
        self.assertEqual(ladder["status"], "ready")
        self.assertEqual(ladder["method"], "traditional_previous_session_hlc")
        self.assertTrue(ladder["S3"] < ladder["S2"] < ladder["S1"] < ladder["P"]
                        < ladder["R1"] < ladder["R2"] < ladder["R3"])
        self.assertEqual(row["reference_ohlc"], {"high": bars[-1].high,
            "low": bars[-1].low, "close": bars[-1].close})

    def test_flat_session_explains_coincident_formula_levels_without_padding(self):
        bars = sample_bars()
        flat = ProviderBar(timestamp=bars[-1].timestamp, open=100, high=100,
            low=100, close=100, volume=0)
        row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
            providers=(vendor(bars[:-1] + (flat,)),))
        self.assertEqual(row["pivot_ladder"]["status"], "flat_session_coincident_levels")
        self.assertEqual([row["pivot_ladder"][key] for key in
            ("P", "S1", "S2", "S3", "R1", "R2", "R3")], [100] * 7)

    def test_real_structure_and_classic_levels_use_one_same_closed_frame(self):
        source = vendor(sample_bars())
        row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW, providers=(source,))
        self.assertEqual(row["status"], "fresh_closed_source")
        self.assertEqual(row["history_bars"], 150)
        self.assertEqual(row["structure"]["lookback_used"], 120)
        self.assertEqual(row["classic_pivot"]["status"], "ready")
        self.assertNotEqual(row["parent_snapshot_id"], row["snapshot_id"])
        self.assertEqual(row["structure"]["snapshot_id"], row["snapshot_id"])
        for key in ("supports", "resistances"):
            for level in row["structure"][key]:
                self.assertLessEqual(datetime.fromisoformat(level["confirmed_at"]),
                                     datetime.fromisoformat(row["as_of"]))
        request = source.fetch.call_args.args[0]
        self.assertEqual(request.bars, 150)
        self.assertEqual(request.as_of.date(), PREVIOUS)

    def test_later_open_or_future_bars_cannot_change_displayed_levels(self):
        past = sample_bars()
        future = ProviderBar(timestamp=NOW, open=1000, high=2000, low=1, close=1500, volume=20)
        base = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
            providers=(vendor(past),))
        changed = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
            providers=(vendor(past + (future,)),))
        self.assertEqual(base["classic_pivot"], changed["classic_pivot"])
        self.assertEqual(base["structure"]["supports"], changed["structure"]["supports"])
        self.assertEqual(base["structure"]["resistances"], changed["structure"]["resistances"])
        self.assertEqual(base["close"], changed["close"])

    def test_stale_provider_is_not_spliced_with_fresh_short_provider(self):
        stale = vendor(sample_bars(previous=PREVIOUS - timedelta(days=1)), source="stale")
        fresh = vendor(sample_bars(8), source="fresh")
        row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW, providers=(stale, fresh))
        self.assertEqual(row["source"], "fresh")
        self.assertEqual(row["history_bars"], 8)
        self.assertTrue(row["structure"]["history_is_shorter_than_requested"])
        self.assertEqual(row["structure"]["lookback_used"], 8)

    def test_insufficient_structure_keeps_actual_classic_pivot(self):
        row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
            providers=(vendor(sample_bars(4)),))
        self.assertEqual(row["classic_pivot"]["status"], "ready")
        self.assertEqual(row["structure"]["status"], "insufficient_history")
        self.assertEqual(row["structure"]["supports"], [])

    def test_invalid_floor_geometry_keeps_structural_context_and_no_negative_targets(self):
        bars = sample_bars()
        bad = ProviderBar(timestamp=bars[-1].timestamp, open=1, high=100, low=1, close=1, volume=20)
        row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
            providers=(vendor(bars[:-1] + (bad,)),))
        self.assertEqual(row["status"], "fresh_closed_source")
        self.assertEqual(row["classic_pivot"], {"status": "unavailable_invalid_price_geometry"})
        self.assertEqual(row["structure"]["status"], "ready")

    def test_missing_source_preserves_symbol_and_fixed_error_class_only(self):
        source = vendor(sample_bars(1))
        source.fetch.side_effect = RuntimeError("private cookie must not leak")
        row = report.read_structure("ASELS", previous=PREVIOUS, now=NOW, providers=(source,))
        self.assertEqual(row["symbol"], "ASELS")
        self.assertEqual(row["status"], "source_unavailable")
        self.assertNotIn("cookie", json.dumps(row))


class PreparedPublicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = tempfile.TemporaryDirectory()
        cls.symbols = load_pinned(Path("config/atc_630_symbols.txt"))
        base = report.read_structure("ASELS", previous=PREVIOUS, now=NOW,
            providers=(vendor(sample_bars()),))

        def reader(symbol, **_):
            row = copy.deepcopy(base)
            row["symbol"] = symbol
            row["structure"]["symbol"] = symbol
            return row

        with patch.object(report, "expected_session", return_value=PREVIOUS):
            cls.packet = report.prepare_report(cls.template.name, now=NOW,
                symbols=cls.symbols, reader=reader)

    @classmethod
    def tearDownClass(cls):
        cls.template.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name) / "packet"
        shutil.copytree(self.template.name, self.folder)
        self.calendar_patch = patch.object(report, "expected_session", return_value=PREVIOUS)
        self.calendar_patch.start()
        self.addCleanup(self.calendar_patch.stop)

    def test_preparation_has_all_630_rows_and_no_message_or_stop_tp(self):
        data = list(csv.DictReader(io.StringIO((self.folder / "report.csv").read_text(encoding="utf-8-sig"))))
        self.assertEqual(len(data), 630)
        self.assertEqual({row["Hisse"] for row in data}, set(self.symbols))
        self.assertFalse((self.folder / "delivery.json").exists())
        self.assertFalse(self.packet["stop_tp_changed"])
        self.assertFalse(self.packet["calibration_used"])
        self.assertIn("KlasikPivot", data[0])
        self.assertIn("YapisalDestek1", data[0])
        self.assertIn("PivotDestek3", data[0])
        self.assertIn("PivotDirenc3", data[0])
        self.assertTrue(all(row["PivotDestek3"] and row["PivotDirenc3"] for row in data))
        self.assertIn("YapisalDestekAciklamasi", data[0])
        self.assertNotIn("bars", self.packet)

    def test_only_missing_sources_are_retried_without_discarding_successes(self):
        calls = []
        good = copy.deepcopy(self.packet["rows"][0])
        def reader(symbol, **_):
            calls.append(symbol)
            if symbol == "AKBNK" and calls.count(symbol) == 1:
                return {"symbol": symbol, "status": "source_unavailable",
                    "structure": {"status": "unavailable_source"},
                    "classic_pivot": {"status": "unavailable_source"},
                    "pivot_ladder": {"method": "traditional_previous_session_hlc", "status": "unavailable_source"}}
            row = copy.deepcopy(good)
            row["symbol"] = symbol
            return row
        with tempfile.TemporaryDirectory() as folder, patch.object(report, "render_png", return_value=b"test-png"):
            result = report.prepare_report(folder, symbols=["ASELS", "AKBNK"], now=NOW,
                reader=reader, retries=2, retry_delay=0)
        self.assertEqual(Counter(calls), {"ASELS": 1, "AKBNK": 2})
        self.assertEqual(result["counts"]["fresh"], 2)
        self.assertEqual(result["source_retry_attempts"], 1)

    def test_valid_official_halt_is_separate_from_missing_and_never_retried(self):
        expected = date(2026, 10, 20)
        now = datetime(2026, 10, 21, 8, 35, tzinfo=IST)
        sources = {symbol: vendor(sample_bars(previous=prior), symbol=symbol)
            for symbol, prior in (("RALYH", date(2026, 10, 19)), ("ASELS", expected))}

        def reader(symbol, **options):
            return report.read_structure(symbol, providers=(sources[symbol],), **options)

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(report, "expected_session", return_value=expected), \
                patch.object(report, "render_png", return_value=b"test-png"):
            result = report.prepare_report(folder, symbols=["ASELS", "RALYH"], now=now,
                reader=reader, retries=2, retry_delay=0)
            self.assertEqual(result["counts"]["fresh"], 1)
            self.assertEqual(result["counts"]["halted"], 1)
            self.assertEqual(result["counts"]["missing"], 0)
            self.assertEqual(result["source_retry_attempts"], 0)
            self.assertTrue(all(source.fetch.call_count == 1 for source in sources.values()))
            rows = list(csv.DictReader(io.StringIO((Path(folder) / "report.csv").read_text(encoding="utf-8-sig"))))
            halted = next(row for row in rows if row["Hisse"] == "RALYH")
            self.assertEqual(halted["KapanisTarihi"], "2026-10-19")
            self.assertEqual(halted["ReferansKapanisTarihi"], "2026-10-19")
            self.assertEqual(halted["BeklenenKapanisTarihi"], "2026-10-20")
            self.assertEqual(halted["PiyasaDurumu"], "official_halt")
            self.assertEqual(halted["ResmiBildirim"], "https://www.kap.org.tr/tr/Bildirim/1684170")
            self.assertIn("Resmî işlem durması 1", (Path(folder) / "summary.txt").read_text(encoding="utf-8"))
            manifest = json.loads((Path(folder) / "manifest.json").read_bytes())
            self.assertIn("atc_market_status.py", manifest["implementation_files"])
            self.assertIn("config/atc_market_events.json", manifest["implementation_files"])

    def test_publish_uses_exact_prepared_files_and_does_not_refetch(self):
        transport = Mock()
        transport.send.side_effect = [101, 102, 103]
        with patch.object(report, "vendor_chain", side_effect=AssertionError("must not fetch")):
            receipt = report.publish_report(self.folder, now=NOW, transport=transport, environ=ENV)
        self.assertEqual(receipt["status"], "sent")
        self.assertEqual(receipt["acknowledged"], {"text": 101, "photo": 102, "csv": 103})
        self.assertEqual(transport.send.call_count, 3)
        for call in transport.send.call_args_list:
            self.assertEqual(call.kwargs["chat_id"], report.CHAT)
            self.assertEqual(call.kwargs["message_thread_id"], 8)

    def test_partial_delivery_resumes_only_unacknowledged_parts(self):
        transport = Mock()
        transport.send.side_effect = [101, RuntimeError("network")]
        with self.assertRaises(RuntimeError):
            report.publish_report(self.folder, now=NOW, transport=transport, environ=ENV)
        receipt = json.loads((self.folder / "delivery.json").read_bytes())
        self.assertEqual(receipt["acknowledged"], {"text": 101})
        next_transport = Mock()
        next_transport.send.side_effect = [102, 103]
        report.publish_report(self.folder, now=NOW, transport=next_transport, environ=ENV)
        self.assertEqual(next_transport.send.call_count, 2)
        repeat = Mock()
        report.publish_report(self.folder, now=NOW, transport=repeat, environ=ENV)
        repeat.send.assert_not_called()

    def test_changed_prepared_text_stops_before_any_message(self):
        (self.folder / "summary.txt").write_text("changed", encoding="utf-8")
        transport = Mock()
        with self.assertRaisesRegex(ValueError, "hash_changed"):
            report.publish_report(self.folder, now=NOW, transport=transport, environ=ENV)
        transport.send.assert_not_called()

    def test_stale_report_is_not_published_as_current(self):
        report.expected_session.return_value = date(2026, 10, 19)
        with self.assertRaisesRegex(ValueError, "current_pinned"):
            report.publish_report(self.folder, now=NOW, transport=Mock(), environ=ENV)

    def test_wrong_existing_destination_is_rejected_before_reading_packet(self):
        with self.assertRaisesRegex(ValueError, "destination"):
            report.publish_report(Path(self.tmp.name) / "absent", transport=Mock(),
                environ={**ENV, "TELEGRAM_TOPIC_REPORTS": "5"})

    def test_insufficient_fresh_coverage_blocks_all_messages(self):
        value = json.loads((self.folder / "report.json").read_bytes())
        for row in value["rows"][:64]:
            row["status"] = "source_unavailable"
        value["counts"]["fresh"] = 566
        report.atomic_json(self.folder / "report.json", value)
        manifest = json.loads((self.folder / "manifest.json").read_bytes())
        manifest["files"]["report.json"] = sha256((self.folder / "report.json").read_bytes()).hexdigest()
        report.atomic_json(self.folder / "manifest.json", manifest)
        transport = Mock()
        with self.assertRaisesRegex(ValueError, "coverage"):
            report.publish_report(self.folder, now=NOW, transport=transport, environ=ENV)
        transport.send.assert_not_called()

    def test_changed_implementation_cannot_reuse_old_prepared_packet(self):
        manifest = json.loads((self.folder / "manifest.json").read_bytes())
        manifest["implementation_files"]["atc_support_resistance.py"] = "0" * 64
        report.atomic_json(self.folder / "manifest.json", manifest)
        with self.assertRaisesRegex(ValueError, "implementation_changed"):
            report.publish_report(self.folder, now=NOW, transport=Mock(), environ=ENV)

    def test_changed_official_notice_config_requires_new_preparation_before_sending(self):
        manifest = json.loads((self.folder / "manifest.json").read_bytes())
        manifest["implementation_files"]["config/atc_market_events.json"] = "0" * 64
        report.atomic_json(self.folder / "manifest.json", manifest)
        sender = Mock()
        with self.assertRaisesRegex(ValueError, "implementation_changed"):
            report.publish_report(self.folder, now=NOW, transport=sender, environ=ENV)
        sender.send.assert_not_called()

    def test_halted_references_never_increase_90_percent_fresh_publication_coverage(self):
        value = json.loads((self.folder / "report.json").read_bytes())
        for row in value["rows"][:64]:
            row["status"] = "official_halt_reference"
        value["counts"].update(fresh=566, halted=64, missing=0)
        report.atomic_json(self.folder / "report.json", value)
        manifest = json.loads((self.folder / "manifest.json").read_bytes())
        manifest["files"]["report.json"] = sha256((self.folder / "report.json").read_bytes()).hexdigest()
        report.atomic_json(self.folder / "manifest.json", manifest)
        sender = Mock()
        with self.assertRaisesRegex(ValueError, "coverage_below_90"):
            report.publish_report(self.folder, now=NOW, transport=sender, environ=ENV)
        sender.send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
