from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from scripts import atc_live_snapshot as live
from tests.test_atc_live_snapshot import IDENTITY, synthetic_reader

IST = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 20, 19, tzinfo=IST)


class LiveSourceRecoveryTests(unittest.TestCase):
    def test_45m_production_never_falls_back_to_derived_grid(self):
        with patch.object(live, "vendor_chain", side_effect=AssertionError("derived source forbidden")):
            providers = live.live_vendor_chain(Timeframe.M45)
        self.assertEqual(len(providers), 2)
        self.assertTrue(all(callable(provider.fetch_native_grid) for provider in providers))
        self.assertTrue(all(provider.native_grid_contract ==
            "tradingview_native_45m_including_auctions" for provider in providers))
        self.assertEqual(type(live.live_vendor_chain("45m")[0]), type(providers[0]))

    def test_retries_only_unavailable_sources_and_keeps_success(self):
        calls = Counter()

        def read(symbol, **kwargs):
            calls[symbol] += 1
            if symbol == "AKBNK" and calls[symbol] < 3:
                return {"symbol": symbol, "status": "source_unavailable", "evaluations": []}
            return synthetic_reader(symbol)

        with tempfile.TemporaryDirectory() as folder, \
                patch.object(live, "implementation_hashes", return_value=IDENTITY), \
                patch.object(live, "render_png", return_value=b"test"):
            report = live.prepare_report(folder, symbols=["ASELS", "AKBNK"],
                reader=read, clock=lambda: NOW)
        self.assertEqual(calls, {"ASELS": 1, "AKBNK": 3})
        self.assertEqual(report["counts"]["missing"], 0)
        self.assertEqual(report["counts"]["calculated"], 2)

    def test_weekly_production_requires_explicit_native_access(self):
        with patch.object(live, "vendor_chain", side_effect=AssertionError("derived source forbidden")):
            providers = live.live_vendor_chain("1wk")
        self.assertTrue(all(callable(provider.fetch_native_weekly) for provider in providers))

    def test_intraday_production_never_falls_back_to_filtered_or_assembled_candles(self):
        for timeframe in ("15m", "30m", "1h", "2h", "4h"):
            with self.subTest(timeframe=timeframe), patch.object(live, "vendor_chain",
                    side_effect=AssertionError("hourly assembly forbidden")):
                providers = live.live_vendor_chain(timeframe)
            self.assertTrue(all(callable(provider.fetch_native_multihour) for provider in providers))

    def test_official_halt_keeps_last_real_source_and_excludes_current_signal(self):
        meta = synthetic_reader("RALYH")["metadata"]
        meta.update(expected_bucket_open="2026-10-20T18:00:00+03:00", received_at=NOW.isoformat())
        frame = SimpleNamespace(source="real-test-source", price_basis=SimpleNamespace(value="split_adjusted"),
            snapshot_id="immutable-test", bars=[SimpleNamespace(
                open_time=datetime(2026, 10, 19, 18, tzinfo=IST), close=42.5)])
        with patch.object(live, "prepare_frame", return_value=(frame, meta)), \
                patch.object(live, "evaluate_frame", return_value=[]):
            row = live.read_symbol("RALYH", timeframe=Timeframe.M45, bindings=[],
                calendar_version="test", clock=lambda: NOW, providers=[SimpleNamespace(name="test")])
        self.assertEqual(row["status"], "available")
        self.assertEqual(row["close"], 42.5)
        self.assertEqual(row["market_event"]["status"], "official_halt")
        self.assertFalse(row["metadata"]["usable_latest"])
        self.assertFalse(row["metadata"]["current_bucket"])
        self.assertEqual(row["metadata"]["last_bar_open"], meta["last_bar_open"])

    def test_preopen_keeps_previous_session_halt_and_resumption_expires_it(self):
        frame = SimpleNamespace(source="real-test-source", price_basis=SimpleNamespace(value="split_adjusted"),
            snapshot_id="immutable-test", bars=[SimpleNamespace(
                open_time=datetime(2026, 10, 19, 18, tzinfo=IST), close=42.5)])
        for hour, expected_session, halted in ((3, "2026-10-20", True), (10, "2026-10-21", False)):
            now = datetime(2026, 10, 21, hour, tzinfo=IST)
            meta = {**synthetic_reader("RALYH")["metadata"],
                "expected_bucket_open": expected_session + "T18:00:00+03:00", "received_at": now.isoformat()}
            with self.subTest(hour=hour), patch.object(live, "prepare_frame", return_value=(frame, meta)), \
                    patch.object(live, "evaluate_frame", return_value=[]):
                row = live.read_symbol("RALYH", timeframe=Timeframe.M45, bindings=[],
                    calendar_version="test", clock=lambda now=now: now, providers=[SimpleNamespace(name="test")])
            self.assertEqual(bool(row.get("market_event")), halted)

    def test_halt_does_not_accept_new_bars_from_the_halted_day(self):
        frame = SimpleNamespace(bars=[SimpleNamespace(open_time=NOW)])
        meta = {"expected_bucket_open": NOW.isoformat(), "received_at": NOW.isoformat()}
        with patch.object(live, "prepare_frame", return_value=(frame, meta)):
            row = live.read_symbol("RALYH", timeframe=Timeframe.M45, bindings=[],
                calendar_version="test", clock=lambda: NOW, providers=[SimpleNamespace(name="test")])
        self.assertEqual(row["status"], "source_unavailable")
        self.assertEqual(row["evaluations"], [])


if __name__ == "__main__":
    unittest.main()
