import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.screener import (
    SCREENS,
    basic_metrics,
    default_options,
    passes_liquidity,
    rank_key,
    run_screen,
    screen_symbol,
)
from src.screener_cli import summary_text
from src.stock_dashboard import calculate_indicators
from src.universe import Universe, load_universe, read_file


def frame(seed: int = 1, bars: int = 520, volatility: float = 0.016, spike: float = 1.0, volume_level: float = 17.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, volatility, bars)))
    volume = rng.lognormal(volume_level, 0.3, bars)
    volume[-1] *= spike
    return pd.DataFrame(
        {"Open": close, "High": close * 1.008, "Low": close * 0.992, "Close": close, "Volume": volume},
        index=pd.bdate_range("2024-01-01", periods=bars),
    )


class MetricsTests(unittest.TestCase):
    def test_basic_metrics_include_cheap_price_action_flags(self) -> None:
        metrics = basic_metrics(calculate_indicators(frame()))
        for key in ("pierced_down", "pierced_up", "stacked", "rvol", "bb_rank", "turnover"):
            self.assertIn(key, metrics)

    def test_pierced_down_detects_recovered_break(self) -> None:
        data = frame(seed=3)
        prior_low = float(data["Low"].iloc[-21:-1].min())
        data.iloc[-1, data.columns.get_loc("Low")] = prior_low * 0.97
        data.iloc[-1, data.columns.get_loc("Close")] = prior_low * 1.01
        metrics = basic_metrics(calculate_indicators(data))
        self.assertTrue(metrics["pierced_down"])

    def test_illiquid_symbol_is_filtered_out(self) -> None:
        options = default_options()
        thin = {"turnover": 1_000.0, "close": 5.0}
        self.assertFalse(passes_liquidity(thin, options))
        self.assertTrue(passes_liquidity({"turnover": 50_000_000.0, "close": 12.0}, options))

    def test_penny_stock_is_filtered_out(self) -> None:
        options = default_options()
        self.assertFalse(passes_liquidity({"turnover": 90_000_000.0, "close": 0.4}, options))


class ScreenTests(unittest.TestCase):
    def test_volume_spike_screen_matches(self) -> None:
        result = screen_symbol("TEST", frame(seed=5, spike=8.0), default_options(), ["hacim_patlamasi"])
        self.assertIsNotNone(result)
        self.assertIn("hacim_patlamasi", result.screens)

    def test_no_match_returns_none(self) -> None:
        self.assertIsNone(screen_symbol("TEST", frame(seed=5), default_options(), ["hacim_patlamasi"]))

    def test_deep_screen_populates_setup_name(self) -> None:
        matched = None
        for seed in range(30):
            result = screen_symbol("TEST", frame(seed=seed, volatility=0.004), default_options(), ["karar_bolgesi"])
            if result:
                matched = result
                break
        self.assertIsNotNone(matched, "sıkışma senaryosunda en az bir eşleşme beklenir")
        self.assertTrue(matched.setup)
        self.assertIn("karar_bolgesi", matched.screens)

    def test_unknown_screen_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            run_screen(["A"], lambda batch: {}, enabled=["olmayan_tarama"])

    def test_ranking_prefers_higher_weighted_score(self) -> None:
        from src.screener import ScreenResult

        many = ScreenResult("A", 10, 1e8, 10, 1.2, 2, 50, screens=["a", "b"], score=5.0)
        loud = ScreenResult("B", 10, 1e8, 10, 5.0, 2, 50, screens=["a"], score=2.0)
        self.assertLess(rank_key(many), rank_key(loud))


class RobustnessTests(unittest.TestCase):
    def test_single_symbol_failure_does_not_stop_the_scan(self) -> None:
        good = frame(seed=2, spike=8.0)
        store = {"OK": good, "BOZUK": pd.DataFrame({"Close": [1.0]})}
        payload = run_screen(["OK", "BOZUK"], lambda batch: {t: store[t] for t in batch}, enabled=["hacim_patlamasi"])
        self.assertEqual(payload["matched"], 1)
        self.assertIn("BOZUK", payload["errors"])

    def test_batch_download_failure_is_recorded_per_symbol(self) -> None:
        def failing(batch):
            raise ConnectionError("ağ hatası")

        payload = run_screen(["A", "B"], failing)
        self.assertEqual(payload["processed"], 0)
        self.assertEqual(set(payload["errors"]), {"A", "B"})

    def test_missing_data_is_reported_not_silently_skipped(self) -> None:
        payload = run_screen(["YOK"], lambda batch: {})
        self.assertEqual(payload["errors"]["YOK"], "veri yok")


class SummaryTests(unittest.TestCase):
    def test_summary_is_produced_even_with_zero_matches(self) -> None:
        payload = {"requested": 600, "processed": 590, "matched": 0, "filtered_out": 120, "errors": {}, "results": []}
        text = summary_text(payload, "borsapy", 300.0)
        self.assertIn("600 sembol", text)
        self.assertIn("koşulları karşılayan sembol bulunamadı", text)

    def test_summary_lists_real_faults_by_name(self) -> None:
        payload = {
            "requested": 10, "processed": 7, "matched": 0, "filtered_out": 0,
            "errors": {"AAA": "ConnectionError", "BBB": "TypeError"},
            "error_kinds": {"ariza": ["AAA", "BBB"]}, "results": [],
        }
        text = summary_text(payload, "borsapy", 10.0)
        self.assertIn("Gerçek hata veren 2 sembol", text)
        self.assertIn("AAA", text)

    def test_summary_caps_long_result_lists(self) -> None:
        results = [
            {"ticker": f"T{index}", "close": 10.0, "rvol": 2.0, "bb_width_percentile": 10.0, "screens": ["hacim_patlamasi"], "setup": ""}
            for index in range(60)
        ]
        payload = {"requested": 600, "processed": 600, "matched": 60, "filtered_out": 0, "errors": {}, "results": results}
        text = summary_text(payload, "borsapy", 100.0)
        self.assertIn("sembol daha", text)
        self.assertNotIn("T59", text)


class UniverseTests(unittest.TestCase):
    def test_file_source_reads_and_cleans_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "list.txt"
            path.write_text("# yorum\nTHYAO\nasels\nTHYAO\nXU100\nAB\n", encoding="utf-8")
            universe = read_file(path)
            self.assertEqual(universe.symbols, ["ASELS", "THYAO"])

    def test_cache_is_used_when_fresh(self) -> None:
        import time

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            cache.write_text(json.dumps({"symbols": ["AAA", "BBB"], "source": "borsapy", "fetched_at": time.time()}), encoding="utf-8")
            universe = load_universe("auto", None, cache_path=cache)
            self.assertEqual(universe.symbols, ["AAA", "BBB"])
            self.assertIn("önbellek", universe.source)

    def test_stale_cache_is_ignored_and_falls_back_to_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            cache.write_text(json.dumps({"symbols": ["ESKI"], "source": "borsapy", "fetched_at": 0}), encoding="utf-8")
            watchlist = Path(directory) / "list.txt"
            watchlist.write_text("THYAO\nASELS\n", encoding="utf-8")
            universe = load_universe("auto", watchlist, cache_path=cache)
            self.assertNotIn("ESKI", universe.symbols)

    def test_universe_size_property(self) -> None:
        self.assertEqual(Universe(["A", "B"], "test", 0.0).size, 2)


class ScreenCatalogueTests(unittest.TestCase):
    def test_every_screen_has_label_and_description(self) -> None:
        for name, screen in SCREENS.items():
            self.assertTrue(screen["label"], name)
            self.assertTrue(screen["description"], name)
            self.assertTrue(callable(screen["cheap"]), name)

    def test_deep_screens_have_a_cheap_prefilter(self) -> None:
        """Pahalı taramalar ucuz ön koşul olmadan tüm evreni yavaşlatır."""
        # Nötr piyasa: bantlar orta genişlikte, RSI 50, yönlülük zayıf, kırılım yok.
        metrics = {
            "bb_rank": 50.0, "rvol": 1.0, "rsi": 50.0, "adx": 15.0, "atr_pct": 2.0,
            "close": 10.0, "turnover": 1e8, "macd_hist": 0.0, "volume": 1e6,
            "pierced_down": False, "pierced_up": False, "stacked": False,
        }
        options = default_options()
        for name, screen in SCREENS.items():
            if screen["deep"]:
                self.assertFalse(screen["cheap"](metrics, options), f"{name} nötr ölçütlerde derin aşamayı tetiklememeli")


if __name__ == "__main__":
    unittest.main()


class ErrorClassificationTests(unittest.TestCase):
    def test_short_history_is_not_treated_as_a_real_failure(self) -> None:
        from src.screener import classify_error

        self.assertEqual(classify_error("ZGYO için en az 120 bar gerekli; yalnızca 60 bar geldi."), "kisa_gecmis")
        self.assertEqual(classify_error("veri yok"), "veri_yok")
        self.assertEqual(classify_error("ConnectionError: ağ kesildi"), "ariza")

    def test_run_screen_groups_errors_by_kind(self) -> None:
        store = {"KISA": pd.DataFrame({"Close": [1.0]}), "OK": frame(seed=2, spike=8.0)}
        payload = run_screen(["KISA", "OK"], lambda batch: {t: store[t] for t in batch}, enabled=["hacim_patlamasi"])
        self.assertIn("error_kinds", payload)
        self.assertTrue(payload["error_kinds"])

    def test_summary_separates_data_gaps_from_real_faults(self) -> None:
        payload = {
            "requested": 600, "processed": 500, "matched": 0, "filtered_out": 50, "errors": {},
            "error_kinds": {"kisa_gecmis": ["A", "B"], "ariza": ["C"]}, "results": [],
        }
        text = summary_text(payload, "borsapy", 600.0)
        self.assertIn("Taranamayan 2 sembol", text)
        self.assertIn("Gerçek hata veren 1 sembol", text)
        self.assertIn("Arıza: 1", text)


class RelativeStrengthTests(unittest.TestCase):
    def test_excess_return_is_positive_when_stock_outperforms(self) -> None:
        from src.screener import excess_return

        index = pd.bdate_range("2024-01-01", periods=100)
        stock = pd.DataFrame({"Close": np.linspace(100, 130, 100)}, index=index)
        benchmark = pd.Series(np.linspace(100, 110, 100), index=index)
        self.assertGreater(excess_return(stock, benchmark), 0)

    def test_missing_benchmark_yields_nan_and_label(self) -> None:
        from src.screener import excess_return, relative_strength_label

        index = pd.bdate_range("2024-01-01", periods=100)
        stock = pd.DataFrame({"Close": np.linspace(100, 130, 100)}, index=index)
        self.assertTrue(np.isnan(excess_return(stock, None)))
        self.assertEqual(relative_strength_label(float("nan")), "Benchmark verisi yok")

    def test_labels_cover_the_range(self) -> None:
        from src.screener import relative_strength_label

        self.assertIn("belirgin güçlü", relative_strength_label(5.0))
        self.assertIn("paralel", relative_strength_label(0.0))
        self.assertIn("belirgin zayıf", relative_strength_label(-5.0))


class PresentationTests(unittest.TestCase):
    def test_setup_name_is_not_repeated_as_a_tag(self) -> None:
        from src.screener_cli import _result_line

        item = {
            "ticker": "AKGRT", "close": 6.3, "rvol": 0.77, "bb_width_percentile": 87.0,
            "screens": ["trend_devami"], "setup": "Trend devamı", "notes": [], "excess_return_20": float("nan"),
        }
        text = " ".join(_result_line(item, {"trend_devami": "Trend devamı"}))
        self.assertEqual(text.count("Trend devamı"), 1)

    def test_late_move_note_is_added_for_wide_bands(self) -> None:
        result = screen_symbol("TEST", frame(seed=11, spike=9.0), default_options(), ["hacim_patlamasi"])
        self.assertIsNotNone(result)
        if result.bb_rank >= 80:
            self.assertTrue(any("geç aşaması" in note for note in result.notes))

    def test_ranking_uses_weighted_score_not_raw_rvol(self) -> None:
        from src.screener import ScreenResult

        strong = ScreenResult("A", 10, 1e8, 10, 0.6, 2, 50, screens=["basarisiz_kirilim"], score=3.0)
        noisy = ScreenResult("B", 10, 1e8, 90, 9.0, 2, 50, screens=["asiri_bolge"], score=1.0)
        self.assertLess(rank_key(strong), rank_key(noisy))


class FrameReuseTests(unittest.TestCase):
    def test_frames_are_kept_only_when_requested(self) -> None:
        store = {"OK": frame(seed=2, spike=8.0)}
        without = run_screen(["OK"], lambda batch: {t: store[t] for t in batch}, enabled=["hacim_patlamasi"])
        self.assertEqual(without["frames"], {})
        with_frames = run_screen(
            ["OK"], lambda batch: {t: store[t] for t in batch}, enabled=["hacim_patlamasi"], keep_frames=True
        )
        self.assertIn("OK", with_frames["frames"])

    def test_kept_frame_matches_the_scanned_data(self) -> None:
        store = {"OK": frame(seed=2, spike=8.0)}
        payload = run_screen(
            ["OK"], lambda batch: {t: store[t] for t in batch}, enabled=["hacim_patlamasi"], keep_frames=True
        )
        self.assertEqual(len(payload["frames"]["OK"]), len(store["OK"]))

    def test_non_matching_symbols_are_not_kept(self) -> None:
        store = {"SESSIZ": frame(seed=5)}
        payload = run_screen(
            ["SESSIZ"], lambda batch: {t: store[t] for t in batch}, enabled=["hacim_patlamasi"], keep_frames=True
        )
        self.assertEqual(payload["frames"], {})


class CounterTests(unittest.TestCase):
    def test_illiquid_and_no_match_are_counted_separately(self) -> None:
        thin = frame(seed=3)
        thin["Volume"] = 1.0
        store = {"CANLI": frame(seed=2, spike=8.0), "SESSIZ": frame(seed=4), "SIG": thin}
        payload = run_screen(list(store), lambda batch: {t: store[t] for t in batch}, enabled=["hacim_patlamasi"])
        self.assertEqual(payload["matched"], 1)
        self.assertEqual(payload["illiquid"], 1)
        self.assertEqual(payload["no_match"], 1)
        self.assertEqual(payload["filtered_out"], 2)

    def test_detailed_screen_reports_the_reason(self) -> None:
        from src.screener import screen_symbol_detailed

        thin = frame(seed=3)
        thin["Volume"] = 1.0
        _, reason = screen_symbol_detailed("SIG", thin, default_options(), ["hacim_patlamasi"])
        self.assertEqual(reason, "illiquid")
        _, reason = screen_symbol_detailed("SESSIZ", frame(seed=4), default_options(), ["hacim_patlamasi"])
        self.assertEqual(reason, "no_match")


class FreshnessTests(unittest.TestCase):
    def test_overnight_scan_is_flagged_as_stale(self) -> None:
        from src.screener import bar_freshness

        index = pd.date_range("2026-08-18 10:00", periods=8, freq="1h")
        data = pd.DataFrame({"Close": range(8)}, index=index)
        result = bar_freshness(data, "1h", pd.Timestamp("2026-08-19 03:11"))
        self.assertTrue(result["stale"])
        self.assertGreater(result["age_minutes"], 600)

    def test_in_session_scan_is_not_stale(self) -> None:
        from src.screener import bar_freshness

        index = pd.date_range("2026-08-18 10:00", periods=8, freq="1h")
        data = pd.DataFrame({"Close": range(8)}, index=index)
        self.assertFalse(bar_freshness(data, "1h", pd.Timestamp("2026-08-18 18:00"))["stale"])

    def test_payload_carries_freshness(self) -> None:
        store = {"OK": frame(seed=2, spike=8.0)}
        payload = run_screen(["OK"], lambda batch: {t: store[t] for t in batch}, enabled=["hacim_patlamasi"])
        self.assertIn("freshness", payload)
        self.assertIn("stale", payload["freshness"])


class NoiseControlTests(unittest.TestCase):
    def test_trend_and_extreme_rsi_require_participation(self) -> None:
        """Seans dışında RVOL sıfıra yakındır; bu taramalar tetiklenmemeli."""
        quiet = {
            "bb_rank": 50.0, "rvol": 0.05, "rsi": 80.0, "adx": 30.0, "atr_pct": 2.0,
            "close": 10.0, "turnover": 1e8, "macd_hist": 0.0, "volume": 1e6,
            "pierced_down": False, "pierced_up": False, "stacked": True,
        }
        options = default_options()
        self.assertFalse(SCREENS["trend_devami"]["cheap"](quiet, options))
        self.assertFalse(SCREENS["asiri_bolge"]["cheap"](quiet, options))
        active = {**quiet, "rvol": 1.4}
        self.assertTrue(SCREENS["trend_devami"]["cheap"](active, options))


class DeepScreenCreditTests(unittest.TestCase):
    def test_all_deep_screens_are_evaluated_once_analysis_ran(self) -> None:
        """Ucuz filtre yalnızca derin analizi tetikler; sonuç tüm koşullara bakar."""
        from unittest.mock import patch

        from src.screener import screen_symbol_detailed

        data = frame(seed=12, spike=8.0)
        fake = {
            "setup": {"name": "Destekte reddedilme / başarısız aşağı kırılım", "bias": "iki yönlü"},
            "duration": {"summary": "3 bardır dar bant"},
            "participation_reading": {},
        }
        with patch("src.screener.deep_context", return_value=fake):
            result, _ = screen_symbol_detailed(
                "TEST", data, default_options(), ["hacim_patlamasi", "basarisiz_kirilim", "karar_bolgesi"]
            )
        self.assertIsNotNone(result)
        self.assertIn("basarisiz_kirilim", result.screens)

    def test_screens_are_not_duplicated(self) -> None:
        from unittest.mock import patch

        from src.screener import screen_symbol_detailed

        fake = {"setup": {"name": "Trend devamı", "bias": "yukarı"}, "duration": {"summary": ""}, "participation_reading": {}}
        with patch("src.screener.deep_context", return_value=fake):
            result, _ = screen_symbol_detailed("TEST", frame(seed=13, spike=8.0), default_options(), ["hacim_patlamasi", "trend_devami"])
        if result:
            self.assertEqual(len(result.screens), len(set(result.screens)))


class FormingBarTests(unittest.TestCase):
    def test_half_finished_hourly_bar_doubles_rvol(self) -> None:
        from src.screener import forming_bar_fraction

        index = pd.date_range("2026-08-19 10:00", periods=3, freq="1h")
        data = pd.DataFrame({"Close": [1, 2, 3]}, index=index)
        self.assertAlmostEqual(forming_bar_fraction(data, "1h", pd.Timestamp("2026-08-19 12:30")), 0.5, places=2)

    def test_completed_bar_is_not_scaled(self) -> None:
        from src.screener import forming_bar_fraction

        index = pd.date_range("2026-08-19 10:00", periods=3, freq="1h")
        data = pd.DataFrame({"Close": [1, 2, 3]}, index=index)
        self.assertEqual(forming_bar_fraction(data, "1h", pd.Timestamp("2026-08-19 13:10")), 1.0)

    def test_unknown_interval_is_not_scaled(self) -> None:
        """Tanımlı olmayan bir aralıkta oranlama yapılmaz."""
        from src.screener import forming_bar_fraction

        index = pd.date_range("2026-08-19 10:00", periods=3, freq="1h")
        data = pd.DataFrame({"Close": [1, 2, 3]}, index=index)
        self.assertEqual(forming_bar_fraction(data, "2h", pd.Timestamp("2026-08-19 15:00")), 1.0)

    def test_very_early_bar_has_a_floor(self) -> None:
        """Barın ilk dakikalarında aşırı büyütme yapılmamalı."""
        from src.screener import forming_bar_fraction

        index = pd.date_range("2026-08-19 10:00", periods=3, freq="1h")
        data = pd.DataFrame({"Close": [1, 2, 3]}, index=index)
        self.assertGreaterEqual(forming_bar_fraction(data, "1h", pd.Timestamp("2026-08-19 12:02")), 0.25)


class CorporateActionTests(unittest.TestCase):
    """BIST'te günlük limit ±%10'dur; aşan hareket düzeltilmemiş veri demektir."""

    def _series(self, factor: float | None = None) -> pd.DataFrame:
        rng = np.random.default_rng(1)
        bars = 200
        close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, bars)))
        if factor:
            close[-3:] = close[-3:] / factor
        return pd.DataFrame(
            {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": np.full(bars, 1e6)},
            index=pd.bdate_range("2026-01-01", periods=bars),
        )

    def test_normal_series_is_not_flagged(self) -> None:
        from src.screener import corporate_action_suspect

        self.assertFalse(corporate_action_suspect(self._series())["suspect"])

    def test_split_is_detected_with_a_reason(self) -> None:
        from src.screener import corporate_action_suspect

        result = corporate_action_suspect(self._series(factor=5))
        self.assertTrue(result["suspect"])
        self.assertIn("bölünme", result["reason"])
        self.assertIn("limit", result["reason"])

    def test_weekly_move_within_cumulative_limit_is_not_flagged(self) -> None:
        """Haftalık barda %18 hareket normaldir; günlük eşik uygulanmamalı."""
        from src.screener import corporate_action_suspect

        frame = self._series()
        frame.iloc[-2, frame.columns.get_loc("Close")] = frame["Close"].iloc[-3] * 1.18
        self.assertFalse(corporate_action_suspect(frame, interval="1wk")["suspect"])

    def test_same_move_is_flagged_on_daily(self) -> None:
        from src.screener import corporate_action_suspect

        frame = self._series()
        frame.iloc[-2, frame.columns.get_loc("Close")] = frame["Close"].iloc[-3] * 1.18
        self.assertTrue(corporate_action_suspect(frame, interval="1d")["suspect"])

    def test_split_is_still_detected_on_weekly(self) -> None:
        from src.screener import corporate_action_suspect

        self.assertTrue(corporate_action_suspect(self._series(factor=5), interval="1wk")["suspect"])

    def test_monthly_check_is_disabled_with_an_explanation(self) -> None:
        """Aylık barda birikimli sınır %700'ü aşar; kontrol anlamını yitirir."""
        from src.screener import corporate_action_suspect

        result = corporate_action_suspect(self._series(factor=5), interval="1mo")
        self.assertFalse(result["suspect"])
        self.assertIn("uygulanmadı", result["reason"])

    def test_suspect_symbol_is_excluded_from_matches(self) -> None:
        store = {"BOLUNDU": self._series(factor=5)}
        payload = run_screen(["BOLUNDU"], lambda batch: {t: store[t] for t in batch})
        self.assertEqual(payload["matched"], 0)
        self.assertIn("BOLUNDU", payload["corporate_actions"])

    def test_unknown_market_is_not_flagged(self) -> None:
        from src.screener import corporate_action_suspect

        self.assertFalse(corporate_action_suspect(self._series(factor=5), market="NASDAQ")["suspect"])


class DailyFormingBarTests(unittest.TestCase):
    def test_daily_bar_is_prorated_during_the_session(self) -> None:
        from src.screener import forming_bar_fraction

        data = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-08-19 09:00")]))
        self.assertLess(forming_bar_fraction(data, "1d", pd.Timestamp("2026-08-19 12:00")), 0.6)

    def test_daily_bar_is_complete_after_the_close(self) -> None:
        from src.screener import forming_bar_fraction

        data = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-08-19 09:00")]))
        self.assertEqual(forming_bar_fraction(data, "1d", pd.Timestamp("2026-08-19 18:30")), 1.0)

    def test_previous_day_bar_is_complete(self) -> None:
        from src.screener import forming_bar_fraction

        data = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-08-19 09:00")]))
        self.assertEqual(forming_bar_fraction(data, "1d", pd.Timestamp("2026-08-20 11:00")), 1.0)


class MultiTimeframeTests(unittest.TestCase):
    def _payload(self, results: list[dict]) -> dict:
        return {
            "requested": 100, "processed": 90, "illiquid": 40, "no_match": 30,
            "errors": {}, "error_kinds": {}, "corporate_actions": [], "freshness": {}, "results": results,
        }

    def _item(self, ticker: str, setup: str, screens: list[str], rvol: float = 2.0) -> dict:
        return {
            "ticker": ticker, "close": 10.0, "rvol": rvol, "bb_width_percentile": 20.0,
            "screens": screens, "setup": setup, "setup_bias": "iki yönlü", "notes": [], "excess_return_20": 1.0,
        }

    def test_symbol_matching_both_timeframes_is_marked(self) -> None:
        from src.screener import merge_interval_results

        merged = merge_interval_results({
            "1h": self._payload([self._item("AAA", "Sıkışma / karar bölgesi", ["sikisma_hacim"])]),
            "1d": self._payload([self._item("AAA", "Sıkışma / karar bölgesi", ["karar_bolgesi"])]),
        })
        entry = merged["results"][0]
        self.assertTrue(entry["multi_timeframe"])
        self.assertEqual(entry["matched_intervals"], ["1h", "1d"])

    def test_same_setup_across_timeframes_scores_higher_than_different(self) -> None:
        from src.screener import merge_interval_results

        same = merge_interval_results({
            "1h": self._payload([self._item("AAA", "Trend devamı", ["trend_devami"])]),
            "1d": self._payload([self._item("AAA", "Trend devamı", ["trend_devami"])]),
        })["results"][0]["score"]
        different = merge_interval_results({
            "1h": self._payload([self._item("BBB", "Trend devamı", ["trend_devami"])]),
            "1d": self._payload([self._item("BBB", "Sıkışma / karar bölgesi", ["trend_devami"])]),
        })["results"][0]["score"]
        self.assertGreater(same, different)

    def test_multi_timeframe_outranks_single(self) -> None:
        from src.screener import merge_interval_results

        merged = merge_interval_results({
            "1h": self._payload([self._item("MULTI", "Trend devamı", ["trend_devami"]), self._item("SOLO", "Tükenme denemesi", ["tukenme"])]),
            "1d": self._payload([self._item("MULTI", "Trend devamı", ["trend_devami"])]),
        })
        self.assertEqual(merged["results"][0]["ticker"], "MULTI")

    def test_screens_from_both_timeframes_are_unioned(self) -> None:
        from src.screener import merge_interval_results

        entry = merge_interval_results({
            "1h": self._payload([self._item("AAA", "Trend devamı", ["trend_devami"])]),
            "1d": self._payload([self._item("AAA", "Trend devamı", ["hacim_patlamasi"])]),
        })["results"][0]
        self.assertEqual(set(entry["screens"]), {"trend_devami", "hacim_patlamasi"})

    def test_errors_and_corporate_actions_are_merged(self) -> None:
        from src.screener import merge_interval_results

        first = self._payload([])
        first["errors"] = {"XXX": "veri yok"}
        first["corporate_actions"] = ["ORGE"]
        second = self._payload([])
        second["corporate_actions"] = ["AKFIS"]
        merged = merge_interval_results({"1h": first, "1d": second})
        self.assertEqual(merged["corporate_actions"], ["AKFIS", "ORGE"])
        self.assertIn("XXX", merged["errors"])


class SlowIntervalFormingBarTests(unittest.TestCase):
    """Devam eden hafta/ay barının hacmi eksiktir; oranlanmazsa RVOL düşük çıkar."""

    def test_midweek_bar_is_partial(self) -> None:
        from src.screener import forming_bar_fraction

        data = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-08-17")]))
        fraction = forming_bar_fraction(data, "1wk", pd.Timestamp("2026-08-20"))
        self.assertLess(fraction, 1.0)
        self.assertGreater(fraction, 0.25)

    def test_completed_week_is_full(self) -> None:
        from src.screener import forming_bar_fraction

        data = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-08-17")]))
        self.assertEqual(forming_bar_fraction(data, "1wk", pd.Timestamp("2026-08-24")), 1.0)

    def test_mid_month_bar_is_partial(self) -> None:
        from src.screener import forming_bar_fraction

        data = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-08-01")]))
        self.assertLess(forming_bar_fraction(data, "1mo", pd.Timestamp("2026-08-10")), 0.5)

    def test_completed_month_is_full(self) -> None:
        from src.screener import forming_bar_fraction

        data = pd.DataFrame({"Close": [1.0]}, index=pd.DatetimeIndex([pd.Timestamp("2026-08-01")]))
        self.assertEqual(forming_bar_fraction(data, "1mo", pd.Timestamp("2026-09-05")), 1.0)


class FiveIntervalMergeTests(unittest.TestCase):
    def test_five_timeframes_merge_and_rank(self) -> None:
        from src.screener import merge_interval_results

        def payload(ticker: str) -> dict:
            return {
                "requested": 10, "processed": 10, "illiquid": 0, "no_match": 0,
                "errors": {}, "error_kinds": {}, "corporate_actions": [], "freshness": {},
                "results": [{
                    "ticker": ticker, "close": 10.0, "rvol": 2.0, "bb_width_percentile": 20.0,
                    "screens": ["trend_devami"], "setup": "Trend devamı", "setup_bias": "yukarı",
                    "notes": [], "excess_return_20": 1.0,
                }],
            }

        merged = merge_interval_results({
            "1h": payload("WIDE"), "4h": payload("WIDE"), "1d": payload("WIDE"),
            "1wk": payload("WIDE"), "1mo": payload("NARROW"),
        })
        top = merged["results"][0]
        self.assertEqual(top["ticker"], "WIDE")
        self.assertEqual(len(top["matched_intervals"]), 4)
        self.assertTrue(top["multi_timeframe"])
