"""Cizim katmani duman testleri (ag baglantisi gerektirmez)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src import indicators as ind
from src.data_sources import resolve_symbol
from src.pipeline import extend_future
from src.plotspec import build_spec, segment_ranges
from src.render_html import render_html
from src.render_png import render_png
from src.theme import get_theme
from tests.test_indicators import synthetic_ohlcv


class TestSymbolRouting(unittest.TestCase):
    def test_bist_default(self) -> None:
        spec = resolve_symbol("THYAO")
        self.assertEqual(spec.provider, "borsapy")
        self.assertEqual(spec.market, "bist")

    def test_dot_is_suffix_routes_to_borsapy(self) -> None:
        self.assertEqual(resolve_symbol("ASELS.IS").query, "ASELS")

    def test_foreign_equity(self) -> None:
        spec = resolve_symbol("AAPL")
        self.assertEqual(spec.provider, "yfinance")

    def test_crypto_pair_and_alias(self) -> None:
        self.assertEqual(resolve_symbol("BTC-USD").market, "crypto")
        self.assertEqual(resolve_symbol("crypto:ETH").query, "ETH-USD")
        self.assertEqual(resolve_symbol("ETH").query, "ETH-USD")

    def test_explicit_prefix_wins(self) -> None:
        self.assertEqual(resolve_symbol("yf:AAPL").provider, "yfinance")
        self.assertEqual(resolve_symbol("bist:GARAN").provider, "borsapy")


class TestSegments(unittest.TestCase):
    def test_segment_ranges(self) -> None:
        colors = pd.Series(["up", "up", "down", "down", "down", "up"])
        self.assertEqual(segment_ranges(colors), [(0, 2, "up"), (2, 5, "down"), (5, 6, "up")])


class TestProjection(unittest.TestCase):
    def test_extend_future_places_raw_spans_ahead(self) -> None:
        df = synthetic_ohlcv(200)
        series = ind.compute(df)
        df_ext, ext = extend_future(df, series, 25)
        self.assertEqual(len(df_ext), len(df) + 25)
        # Uzatilan bolgede fiyat yok, bulut var
        self.assertTrue(df_ext["Close"].iloc[-1] != df_ext["Close"].iloc[-1])  # NaN
        self.assertFalse(pd.isna(ext["ICH_span_a"].iloc[-1]))
        self.assertAlmostEqual(
            float(ext["ICH_span_a"].iloc[len(df)]), float(series["ICH_span_a_raw"].iloc[-25])
        )

    def test_extend_future_is_noop_without_ichimoku(self) -> None:
        df = synthetic_ohlcv(120)
        series = ind.compute(df, keys=("ma", "rsi"))
        df_ext, ext = extend_future(df, series, 25)
        self.assertEqual(len(df_ext), len(df))


class TestViews(unittest.TestCase):
    def test_every_view_has_valid_keys(self) -> None:
        from src.plotspec import _OVERLAY_BUILDERS, _PANEL_BUILDERS
        from src.views import VIEWS

        valid = set(_OVERLAY_BUILDERS) | set(_PANEL_BUILDERS)
        for view in VIEWS:
            self.assertTrue(set(view.keys) <= valid, f"{view.key}: {set(view.keys) - valid}")
            self.assertTrue(set(view.compute_keys) <= set(ind.ALL_INDICATORS), view.key)

    def test_grid_views_match_requested_indicator_schemas(self) -> None:
        from src.views import GRID_SET, VIEWS_BY_KEY

        expected = {
            "bollinger_macd": ("bbands", "macd", "smi", "obv", "candles"),
            "ichimoku_rsi": ("ichimoku", "rsi", "cci", "atr", "candles"),
            "sar_vwap": ("sar", "vwap", "stochrsi", "adx", "candles"),
            "supertrend_fisher": ("supertrend", "fisher", "cmf", "momentum", "candles"),
        }
        self.assertEqual(tuple(expected), GRID_SET)
        for key, keys in expected.items():
            self.assertEqual(VIEWS_BY_KEY[key].keys, keys)

    def test_default_views_do_not_repeat_an_indicator(self) -> None:
        from src.views import GRID_SET, VIEWS_BY_KEY

        used = [
            key for view_key in GRID_SET
            for key in VIEWS_BY_KEY[view_key].keys
            if key != "candles"
        ]
        self.assertEqual(len(used), len(set(used)))

    def test_latest_candle_badge_is_available_in_each_default_view(self) -> None:
        from src.views import GRID_SET, VIEWS_BY_KEY

        self.assertTrue(all("candles" in VIEWS_BY_KEY[key].keys for key in GRID_SET))

    def test_default_views_follow_requested_overlay_panel_layout(self) -> None:
        from src.plotspec import _OVERLAY_BUILDERS, _PANEL_BUILDERS
        from src.views import GRID_SET, VIEWS_BY_KEY

        expected = {
            "bollinger_macd": (2, 3),
            "ichimoku_rsi": (2, 3),
            "sar_vwap": (3, 2),
            "supertrend_fisher": (2, 3),
        }
        for key in GRID_SET:
            view = VIEWS_BY_KEY[key]
            overlays = [k for k in view.keys if k in _OVERLAY_BUILDERS]
            panels = [k for k in view.keys if k in _PANEL_BUILDERS]
            self.assertEqual((len(overlays), len(panels)), expected[key], key)

    def test_candlestick_overlay_keeps_only_latest_two_bars(self) -> None:
        from src.plotspec import _recent_candle_series

        numeric = pd.Series([1.0, 2.0, 3.0, 4.0])
        labels = pd.Series(["A", "B", "C", "D"], dtype="object")
        recent_numeric = _recent_candle_series(numeric)
        recent_labels = _recent_candle_series(labels)
        self.assertTrue(recent_numeric.iloc[:-2].isna().all())
        self.assertEqual(recent_numeric.iloc[-2:].tolist(), [3.0, 4.0])
        self.assertEqual(recent_labels.tolist(), ["", "", "C", "D"])

    def test_compute_keys_deduplicated(self) -> None:
        from src.plotspec import compute_keys_for

        self.assertEqual(compute_keys_for(("bbands", "bbstate", "bbwidth")), ("bbands",))
        self.assertEqual(compute_keys_for(("volume", "rvol")), ("volume",))


class TestRenderers(unittest.TestCase):
    def setUp(self) -> None:
        self.keys = ("ma", "bbands", "supertrend", "ichimoku", "vwap",
                     "volume", "rsi", "macd", "stochrsi", "adx")
        self.df = synthetic_ohlcv(320)
        series = ind.compute(self.df, keys=self.keys)
        df, series = extend_future(self.df, series, 25)
        self.spec = build_spec(df, series, self.keys, "TEST", "sentetik veri",
                               note="genel bakis")

    def test_spec_panels_follow_key_order(self) -> None:
        self.assertEqual([p.key for p in self.spec.panels],
                         ["volume", "rsi", "macd", "stochrsi", "adx"])
        self.assertGreaterEqual(len(self.spec.overlays), 8)
        self.assertGreaterEqual(len(self.spec.snapshot), 6)

    def test_png_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = render_png(self.spec, get_theme("ink"), Path(tmp) / "t.png", width_px=1400)
            self.assertGreater(path.stat().st_size, 50_000)

    def test_html_single_frame(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = render_html(
                [("tumu", "Tümü", "not", self.spec)], get_theme("ink"),
                Path(tmp) / "t.html", ticker="TEST", subtitle="sentetik",
                source="test", generated="now",
            )
            body = path.read_text(encoding="utf-8")
            self.assertIn("plotly", body.lower())
            self.assertIn("TEST", body)
            self.assertGreater(len(body), 100_000)

    def test_html_tabs_load_plotly_once(self) -> None:
        """Cok kareli sayfada plotly.js tek kez yuklenmeli, aksi halde dosya sisiyor."""
        frames = [(f"k{i}", f"Kare {i}", "not", self.spec) for i in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            path = render_html(
                frames, get_theme("ink"), Path(tmp) / "t.html", ticker="TEST",
                subtitle="sentetik", source="test", generated="now",
            )
            body = path.read_text(encoding="utf-8")
            self.assertEqual(body.count("cdn.plot.ly"), 1)
            self.assertEqual(body.count('role="tab"'), 3)
            self.assertEqual(body.count('class="frame"'), 3)

    def test_html_rejects_empty_frames(self) -> None:
        with self.assertRaises(ValueError):
            render_html([], get_theme("ink"), "x.html", ticker="T", subtitle="",
                        source="", generated="")

    def test_paper_theme_renders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            render_png(self.spec, get_theme("paper"), Path(tmp) / "p.png", width_px=1200)


if __name__ == "__main__":
    unittest.main()


class TestCLIArgs(unittest.TestCase):
    def test_resolve_keys_all(self) -> None:
        from src.cli import resolve_keys

        self.assertEqual(resolve_keys("all"), ind.ALL_INDICATORS)
        self.assertEqual(resolve_keys(" MA , rsi "), ("ma", "rsi"))

    def test_resolve_keys_rejects_unknown(self) -> None:
        from src.cli import resolve_keys

        with self.assertRaises(SystemExit):
            resolve_keys("ma,bogus")

    def test_parse_args_defaults(self) -> None:
        from src.cli import parse_args

        args = parse_args(["--symbol", "THYAO"])
        self.assertEqual((args.interval, args.theme), ("1d", "tv"))
        self.assertIsNone(args.bars)  # araliga gore secilir
        self.assertEqual(args.grid, 0)

    def test_default_bars_scale_with_interval(self) -> None:
        """Aylikta 250 bar 20 yil demektir; mumlar bir piksele iner."""
        from src.pipeline import default_bars

        self.assertEqual(default_bars("1d"), 170)
        self.assertLess(default_bars("1wk"), default_bars("1d"))
        self.assertLess(default_bars("1mo"), default_bars("1wk"))
        self.assertEqual(default_bars("bilinmeyen"), 250)

    def test_explicit_bars_wins(self) -> None:
        from src.cli import parse_args

        args = parse_args(["--symbol", "X", "--bars", "80"])
        self.assertEqual(args.bars, 80)


class TestPipelineViews(unittest.TestCase):
    """Veri kaynagini sahte veriyle degistirip uctan uca akisi dogrular."""

    def setUp(self) -> None:
        import src.pipeline as pipeline
        from src.data_sources import SymbolSpec

        self._original = pipeline.fetch_ohlcv
        pipeline.fetch_ohlcv = lambda symbol, period="1y", interval="1d", bars=None: (
            synthetic_ohlcv(520, seed=3),
            SymbolSpec(symbol, "borsapy", "TEST", "bist", "TEST"),
        )
        self.pipeline = pipeline

    def tearDown(self) -> None:
        self.pipeline.fetch_ohlcv = self._original

    def test_build_views_produces_one_spec_per_view(self) -> None:
        from src.views import resolve_views

        views = resolve_views("set")
        result = self.pipeline.build_views("TEST", views, bars=200)
        self.assertEqual(len(result), len(views))
        self.assertEqual([r.key for r in result], [v.key for v in views])

    def test_all_views_share_one_x_range(self) -> None:
        """Izgarada karolarin x eksenleri hizali olmali."""
        from src.views import resolve_views

        result = self.pipeline.build_views("TEST", resolve_views("grid"), bars=200)
        lengths = {len(r.spec.df) for r in result}
        self.assertEqual(len(lengths), 1, "kareler farkli x araligina sahip")
        # Ichimoku iceren set 25 bar ileri uzatilir
        self.assertEqual(lengths.pop(), 225)

    def test_set_without_cloud_is_not_extended(self) -> None:
        from src.views import resolve_views

        result = self.pipeline.build_views("TEST", resolve_views("klasik,trend"), bars=200)
        self.assertEqual({len(r.spec.df) for r in result}, {200})

    def test_snapshot_identical_across_views(self) -> None:
        """Ayni bar, ayni ozet: kareler arasinda tutarsiz rakam gorunmemeli."""
        from src.views import resolve_views

        result = self.pipeline.build_views("TEST", resolve_views("set"), bars=200)
        first = dict((label, value) for label, value, _ in result.results[0].spec.snapshot)
        for other in result.results[1:]:
            values = dict((label, value) for label, value, _ in other.spec.snapshot)
            self.assertEqual(first["Son"], values["Son"], other.key)



class TestCompose(unittest.TestCase):
    def test_grid_dimensions_and_row_alignment(self) -> None:
        """Farkli yukseklikteki karolar satir bazinda hizalanmali."""
        from PIL import Image

        from src.compose import compose_grid

        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for i, height in enumerate((400, 500, 420, 420)):
                path = Path(tmp) / f"t{i}.png"
                Image.new("RGB", (600, height), "#101010").save(path)
                paths.append(path)

            out = compose_grid(paths, Path(tmp) / "grid.png", get_theme("tv"),
                               columns=2, title="TEST", subtitle="alt")
            with Image.open(out) as im:
                # 2 sutun x 600 + bosluklar + kenar paylari
                self.assertEqual(im.width, 22 * 2 + 600 * 2 + 18)
                # satir yukseklikleri: max(400,500)=500, max(420,420)=420
                self.assertEqual(im.height, 22 * 2 + 78 + 500 + 420 + 18)

    def test_grid_rejects_empty_input(self) -> None:
        from src.compose import compose_grid

        with self.assertRaises(ValueError):
            compose_grid([], "x.png", get_theme("tv"))


class TestFrameShape(unittest.TestCase):
    """Izgara kareleri kullanıcının dört şemasını korumalı."""

    def test_rendered_spec_matches_requested_panels(self) -> None:
        import src.pipeline as pipeline
        from src.data_sources import SymbolSpec
        from src.views import resolve_views

        expected_panels = {
            "bollinger_macd": 3,
            "ichimoku_rsi": 3,
            "sar_vwap": 2,
            "supertrend_fisher": 3,
        }
        original = pipeline.fetch_ohlcv
        pipeline.fetch_ohlcv = lambda symbol, period="1y", interval="1d", bars=None: (
            synthetic_ohlcv(520, seed=5),
            SymbolSpec(symbol, "borsapy", "TEST", "bist", "TEST"),
        )
        try:
            result = pipeline.build_views("TEST", resolve_views("grid"), bars=150)
            for item in result:
                self.assertEqual(len(item.spec.panels), expected_panels[item.key], item.key)
        finally:
            pipeline.fetch_ohlcv = original


class TestTelegramPayload(unittest.TestCase):
    """Istek govdesini agsiz dogrular: requests.post yakalanir."""

    def _capture(self, env: dict) -> dict:
        import os
        from unittest import mock

        from src import telegram

        captured: dict = {}

        class FakeResponse:
            status_code = 200
            content = b"{}"

            @staticmethod
            def json() -> dict:
                return {"ok": True, "result": {}}

        def fake_post(url, data=None, files=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            captured["files"] = files
            return FakeResponse()

        with mock.patch.dict(os.environ, env, clear=False), \
                mock.patch.object(telegram.requests, "post", fake_post), \
                tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.png"
            path.write_bytes(b"\x89PNG\r\n")
            telegram.send_document(path, "başlık")
        return captured

    def test_topic_id_is_sent_as_message_thread_id(self) -> None:
        captured = self._capture({
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_CHAT_ID": "-1003502567927",
            "TELEGRAM_TOPIC_ID": "18",
        })
        self.assertEqual(captured["data"]["chat_id"], "-1003502567927")
        self.assertEqual(captured["data"]["message_thread_id"], "18")
        self.assertIn("sendDocument", captured["url"])

    def test_topic_id_omitted_when_unset(self) -> None:
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"TELEGRAM_TOPIC_ID": ""}, clear=False):
            captured = self._capture({
                "TELEGRAM_BOT_TOKEN": "123:ABC",
                "TELEGRAM_CHAT_ID": "-100999",
                "TELEGRAM_TOPIC_ID": "",
            })
        self.assertNotIn("message_thread_id", captured["data"])

    def test_missing_credentials_raise(self) -> None:
        import os
        from unittest import mock

        from src.telegram import TelegramError, send_photo

        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "",
                                          "TELEGRAM_CHAT_ID": ""}, clear=False):
            with self.assertRaises(TelegramError):
                send_photo("yok.png")


class TestOpenBarAndScale(unittest.TestCase):
    def _daily(self) -> pd.DatetimeIndex:
        """BIST gunluk barlari 09:00 damgasi tasir."""
        return pd.DatetimeIndex([pd.Timestamp(f"2026-08-{d} 09:00")
                                 for d in (17, 18, 19, 20)])

    def test_open_bar_detection(self) -> None:
        from src.pipeline import last_bar_is_open

        idx = self._daily()
        self.assertTrue(last_bar_is_open(idx, pd.Timestamp("2026-08-20 12:27")))
        self.assertFalse(last_bar_is_open(idx, pd.Timestamp("2026-08-21 09:30")))

    def test_daily_bar_closes_at_session_end_not_next_morning(self) -> None:
        """Seans 18:00'de biter; bar ertesi sabaha kadar acik gorunmemeli."""
        from src.pipeline import last_bar_is_open

        idx = self._daily()
        self.assertTrue(last_bar_is_open(idx, pd.Timestamp("2026-08-20 17:00")))
        self.assertFalse(last_bar_is_open(idx, pd.Timestamp("2026-08-20 22:41")))

    def test_weekly_bar_open_until_friday_close(self) -> None:
        from src.pipeline import last_bar_is_open

        weekly = pd.DatetimeIndex([pd.Timestamp(f"2026-{m} 09:00")
                                   for m in ("07-27", "08-03", "08-10", "08-17")])
        # Persembe aksami: hafta henuz bitmedi
        self.assertTrue(last_bar_is_open(weekly, pd.Timestamp("2026-08-20 22:41")))
        # Cumartesi: cuma kapanisi gecti
        self.assertFalse(last_bar_is_open(weekly, pd.Timestamp("2026-08-22 12:00")))

    def test_crypto_has_no_session_close(self) -> None:
        from src.pipeline import last_bar_is_open

        idx = pd.DatetimeIndex([pd.Timestamp(f"2026-08-{d}") for d in (17, 18, 19, 20)])
        self.assertTrue(last_bar_is_open(idx, pd.Timestamp("2026-08-20 22:41"),
                                         market="crypto"))
        self.assertFalse(last_bar_is_open(idx, pd.Timestamp("2026-08-20 22:41"),
                                          market="bist"))

    def test_intraday_uses_duration_only(self) -> None:
        from src.pipeline import last_bar_is_open

        hourly = pd.DatetimeIndex([pd.Timestamp(f"2026-08-20 {h}:00") for h in (9, 13, 17)])
        self.assertTrue(last_bar_is_open(hourly, pd.Timestamp("2026-08-20 18:30")))
        self.assertFalse(last_bar_is_open(hourly, pd.Timestamp("2026-08-20 22:41")))

    def test_open_bar_needs_enough_history(self) -> None:
        from src.pipeline import last_bar_is_open

        self.assertFalse(last_bar_is_open(pd.DatetimeIndex(["2026-08-20"])))

    def test_log_scale_triggers_on_wide_range(self) -> None:
        from src.plotspec import needs_log_scale

        narrow = synthetic_ohlcv(200, seed=4)
        self.assertFalse(needs_log_scale(narrow))

        wide = narrow.copy()
        wide[["Open", "High", "Low", "Close"]] *= np.exp(
            np.linspace(0, 2.5, len(wide))
        )[:, None]
        self.assertTrue(needs_log_scale(wide))

    def test_explicit_scale_overrides_auto(self) -> None:
        from src.plotspec import build_spec

        df = synthetic_ohlcv(200, seed=4)
        series = ind.compute(df, keys=("ma",))
        self.assertTrue(build_spec(df, series, ("ma",), "T", "s", log_price=True).log_price)
        self.assertFalse(build_spec(df, series, ("ma",), "T", "s", log_price=False).log_price)

    def test_scale_flag_mapping(self) -> None:
        from src.cli import _scale

        self.assertIsNone(_scale("auto"))
        self.assertTrue(_scale("log"))
        self.assertFalse(_scale("linear"))


class TestOutlierClipping(unittest.TestCase):
    def test_single_spike_sets_a_cap(self) -> None:
        from src.plotspec import clip_outliers

        rng = np.random.default_rng(1)
        series = pd.Series(list(rng.lognormal(13, 0.3, 200)) + [5e8])
        cap, exceeding = clip_outliers(series)
        self.assertTrue(np.isfinite(cap))
        self.assertGreaterEqual(exceeding, 1)
        self.assertLess(cap, float(series.max()))

    def test_even_series_is_not_clipped(self) -> None:
        from src.plotspec import clip_outliers

        series = pd.Series(np.random.default_rng(2).normal(100, 3, 200))
        cap, exceeding = clip_outliers(series)
        self.assertTrue(np.isnan(cap))
        self.assertEqual(exceeding, 0)

    def test_short_series_is_not_clipped(self) -> None:
        from src.plotspec import clip_outliers

        self.assertEqual(clip_outliers(pd.Series([1.0, 2.0, 900.0]))[1], 0)

    def test_volume_panel_reports_clipping(self) -> None:
        from src.plotspec import _volume_panel

        df = synthetic_ohlcv(200, seed=6)
        df.iloc[-3, df.columns.get_loc("Volume")] = float(df["Volume"].max()) * 60
        series = ind.compute(df, keys=("volume",))
        panel = _volume_panel(df, series)
        self.assertIn("kırpıldı", panel.params)
        self.assertIsNotNone(panel.yrange)
        # Kirpilan bar farkli renkte isaretlenmeli
        self.assertIn("accent2", list(panel.traces[0].colors))


class TestPanelClippingApplied(unittest.TestCase):
    """Kirpma mantigi panellere GERCEKTEN baglanmis mi.

    clip_outliers dogru calisip panel onu kullanmazsa kirpma sessizce
    devre disi kalir; bu test o durumu yakalar.
    """

    def setUp(self) -> None:
        df = synthetic_ohlcv(300, seed=17)
        df.iloc[-120, df.columns.get_loc("Volume")] *= 45
        self.df = df
        self.series = ind.compute(df, keys=("volume",))

    def test_rvol_panel_uses_cap(self) -> None:
        from src.plotspec import _rvol_panel

        panel = _rvol_panel(self.series)
        self.assertIsNotNone(panel.yrange, "RVOL paneli kirpma uygulamiyor")
        self.assertLess(panel.yrange[1], float(self.series["RVOL"].max()))
        self.assertIn("kırpıldı", panel.params)

    def test_volume_panel_uses_cap(self) -> None:
        from src.plotspec import _volume_panel

        panel = _volume_panel(self.df, self.series)
        self.assertIsNotNone(panel.yrange, "Hacim paneli kirpma uygulamiyor")
        self.assertLess(panel.yrange[1], float(self.series["VOL"].max()))


class TestResampling(unittest.TestCase):
    """4 saatlik barlar saatlikten turetilir; gun sinirlari korunmali."""

    def _hourly(self, days: int = 3, per_day: int = 8) -> pd.DataFrame:
        stamps = [
            pd.Timestamp("2026-08-17 10:00") + pd.Timedelta(days=d, hours=h)
            for d in range(days) for h in range(per_day)
        ]
        n = len(stamps)
        return pd.DataFrame(
            {"Open": np.arange(n, dtype=float) + 1,
             "High": np.arange(n, dtype=float) + 2,
             "Low": np.arange(n, dtype=float),
             "Close": np.arange(n, dtype=float) + 1.5,
             "Volume": np.full(n, 10.0)},
            index=pd.DatetimeIndex(stamps),
        )

    def test_ohlc_aggregation(self) -> None:
        from src.data_sources import resample_bars

        out = resample_bars(self._hourly(days=1), 4)
        self.assertEqual(len(out), 2)
        first = out.iloc[0]
        self.assertEqual(first["Open"], 1.0)      # ilk barin acilisi
        self.assertEqual(first["Close"], 4.5)     # dorduncu barin kapanisi
        self.assertEqual(first["High"], 5.0)      # en yuksek
        self.assertEqual(first["Low"], 0.0)       # en dusuk
        self.assertEqual(first["Volume"], 40.0)   # toplam

    def test_days_never_merge(self) -> None:
        """Kritik: bir gunun son bari ertesi gunun ilkiyle birlesmemeli."""
        from src.data_sources import resample_bars

        out = resample_bars(self._hourly(days=3), 4)
        self.assertEqual(len(out), 6)  # gunde 2, uc gun
        self.assertEqual(sorted(out.index.normalize().unique().tolist()),
                         sorted(pd.DatetimeIndex([
                             "2026-08-17", "2026-08-18", "2026-08-19"]).tolist()))

    def test_orphan_bucket_merges_into_previous(self) -> None:
        """BIST saatlik veride gunde 9 bar gelir; 4+4+1 degil 4+5 olmali.

        Yoksa tek saatlik bar sahte bir '4 saatlik' bar gibi gorunur ve
        acilis=yuksek=dusuk=kapanis olan bos bir mum cizilir.
        """
        from src.data_sources import resample_bars

        out = resample_bars(self._hourly(days=2, per_day=9), 4)
        self.assertEqual(len(out), 4)  # gunde 2
        counts = out.groupby(out.index.normalize()).size().unique().tolist()
        self.assertEqual(counts, [2])
        self.assertEqual(out.iloc[1]["Volume"], 50.0)  # 5 saatlik ikinci kova

    def test_partial_day_still_forms_a_bar(self) -> None:
        """Gun daha yeni basladiysa (tek kova) bar yine de olusmali."""
        from src.data_sources import resample_bars

        out = resample_bars(self._hourly(days=1, per_day=3), 4)
        self.assertEqual(len(out), 1)
        self.assertEqual(out.iloc[0]["Volume"], 30.0)

    def test_factor_one_is_identity(self) -> None:
        from src.data_sources import resample_bars

        df = self._hourly(days=1)
        pd.testing.assert_frame_equal(resample_bars(df, 1), df)


class TestMultiInterval(unittest.TestCase):
    def test_interval_list_parsing(self) -> None:
        from src.cli import _intervals

        self.assertEqual(_intervals("4h,1d,1wk"), ["4h", "1d", "1wk"])
        self.assertEqual(_intervals(" 1d , 1d ,1wk "), ["1d", "1wk"])

    def test_space_separated_also_works(self) -> None:
        from src.cli import _intervals

        self.assertEqual(_intervals("4h 1d 1wk"), ["4h", "1d", "1wk"])

    def test_unknown_interval_rejected(self) -> None:
        from src.cli import _intervals

        with self.assertRaises(SystemExit):
            _intervals("7h")
        with self.assertRaises(SystemExit):
            _intervals("  ")

    def test_powershell_literal_mangling_gets_a_hint(self) -> None:
        """PowerShell tirnaksiz '1d' ifadesini 1'e cevirir; mesaj bunu acikla."""
        from src.cli import _intervals

        with self.assertRaises(SystemExit) as ctx:
            _intervals("4h,1,1wk")
        self.assertIn("tırnak", str(ctx.exception))

    def test_synthetic_intervals_declared(self) -> None:
        from src.data_sources import SYNTHETIC_INTERVALS
        from src.pipeline import DEFAULT_PERIODS, INTERVAL_LABELS

        for key in SYNTHETIC_INTERVALS:
            self.assertIn(key, DEFAULT_PERIODS, key)
            self.assertIn(key, INTERVAL_LABELS, key)


class TestBotCommands(unittest.TestCase):
    """Bot komut ayristirma ve guvenlik kontrolu (ag yok)."""

    def test_parse_command(self) -> None:
        from src.bot import _parse

        self.assertEqual(_parse("/grafik TMPOL"), ("grafik", ["TMPOL"]))
        self.assertEqual(_parse("/grafik TMPOL 4h,1d"), ("grafik", ["TMPOL", "4h,1d"]))
        self.assertEqual(_parse("/GrafikYardim"), ("grafikyardim", []))
        self.assertEqual(_parse("merhaba"), ("", []))

    def test_command_addressed_to_us_is_accepted(self) -> None:
        from src.bot import _parse

        self.assertEqual(_parse("/grafik@ChartLabBot ASELS", "chartlabbot"),
                         ("grafik", ["ASELS"]))

    def test_command_addressed_to_another_bot_is_ignored(self) -> None:
        """Grupta baska bot varsa onun komutuna cevap vermemeliyiz."""
        from src.bot import _parse

        self.assertEqual(_parse("/grafik@DigerBot ASELS", "chartlabbot"), ("", []))

    def test_bare_shared_command_is_ignored(self) -> None:
        """/yardim iki botta da var; adressiz gelirse ikisi birden cevap verirdi."""
        from src.bot import _parse

        self.assertEqual(_parse("/yardim", "chartlabbot"), ("", []))
        self.assertEqual(_parse("/yardim@ChartLabBot", "chartlabbot"), ("yardim", []))

    def test_unknown_username_still_serves_unaddressed_own_commands(self) -> None:
        """getMe basarisiz olsa bile /grafik calismaya devam etmeli."""
        from src.bot import _parse

        self.assertEqual(_parse("/grafik X", ""), ("grafik", ["X"]))

    def test_only_configured_chat_is_served(self) -> None:
        """Botun token'ini bilen biri onu baska gruba ekleyebilir."""
        import os
        from unittest import mock

        from src.bot import _allowed

        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "-100123",
                                          "TELEGRAM_TOPIC_ID": ""}):
            self.assertTrue(_allowed({"chat": {"id": -100123}}))
            self.assertFalse(_allowed({"chat": {"id": -100999}}))
            self.assertFalse(_allowed({"chat": {}}))

    def test_only_configured_topic_is_served(self) -> None:
        """Forum grubunda bot her konuda cevap vermemeli."""
        import os
        from unittest import mock

        from src.bot import _allowed

        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "-100123",
                                          "TELEGRAM_TOPIC_ID": "18"}):
            self.assertTrue(_allowed({"chat": {"id": -100123},
                                      "message_thread_id": 18}))
            self.assertFalse(_allowed({"chat": {"id": -100123},
                                       "message_thread_id": 5}))
            # Konu kisiti varken genel akistan gelen komut da islenmez
            self.assertFalse(_allowed({"chat": {"id": -100123}}))

    def test_no_chat_id_configured_blocks_everything(self) -> None:
        import os
        from unittest import mock

        from src.bot import _allowed

        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": ""}):
            self.assertFalse(_allowed({"chat": {"id": -100123}}))

    def test_unknown_command_is_ignored(self) -> None:
        from unittest import mock

        from src import bot

        with mock.patch.object(bot.tg, "get_me", lambda: "chartlabbot"), \
                mock.patch.object(bot.tg, "send_message") as send:
            bot.handle({"text": "/baskabirsey", "chat": {"id": 1}})
            send.assert_not_called()

    def test_other_bots_command_gets_no_reply(self) -> None:
        """Diger botun komutuna 'bilinmeyen komut' bile yazmamaliyiz."""
        from unittest import mock

        from src import bot

        with mock.patch.object(bot.tg, "get_me", lambda: "chartlabbot"), \
                mock.patch.object(bot.tg, "send_message") as send:
            bot.handle({"text": "/rapor THYAO 4h", "chat": {"id": 1}})
            send.assert_not_called()

    def test_grafik_without_symbol_asks_for_one(self) -> None:
        from unittest import mock

        from src import bot

        with mock.patch.object(bot.tg, "get_me", lambda: ""), \
                mock.patch.object(bot.tg, "send_message") as send:
            bot.handle({"text": "/grafik", "chat": {"id": 1}})
            send.assert_called_once()
            self.assertIn("Sembol", send.call_args[0][0])

    def test_bad_interval_is_reported_before_any_work(self) -> None:
        from unittest import mock

        from src import bot

        with mock.patch.object(bot.tg, "get_me", lambda: ""), \
                mock.patch.object(bot.tg, "send_message") as send, \
                mock.patch.object(bot, "_render_and_send") as render:
            bot.handle({"text": "/grafik TMPOL 7h", "chat": {"id": 1}})
            render.assert_not_called()
            self.assertIn("Bilinmeyen aralık", send.call_args[0][0])

    def test_default_intervals_used_when_omitted(self) -> None:
        from unittest import mock

        from src import bot

        with mock.patch.object(bot.tg, "get_me", lambda: ""), \
                mock.patch.object(bot.tg, "send_message"), \
                mock.patch.object(bot, "_render_and_send") as render:
            bot.handle({"text": "/grafik tmpol", "chat": {"id": 1}})
            symbol, intervals, _ = render.call_args[0]
            self.assertEqual(symbol, "TMPOL")  # buyuk harfe cevrilir
            self.assertEqual(intervals, list(bot.DEFAULT_INTERVALS))

    def test_thread_id_is_passed_through(self) -> None:
        """Cevap, komutun geldigi konuya dusmeli."""
        from unittest import mock

        from src import bot

        with mock.patch.object(bot.tg, "get_me", lambda: ""), \
                mock.patch.object(bot.tg, "send_message"), \
                mock.patch.object(bot, "_render_and_send") as render:
            bot.handle({"text": "/grafik X 1d", "chat": {"id": 1},
                        "message_thread_id": 18})
            self.assertEqual(render.call_args[0][2], "18")


class TestPollOnce(unittest.TestCase):
    """Zamanlanmis calistirma: bekleyen komutlari isle, onayla, cik."""

    def setUp(self) -> None:
        """Offset dosyasi yalitilmali; yoksa testler birbirini etkiler."""
        from unittest import mock

        from src import bot

        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(bot, "STATE_FILE",
                                    Path(self._tmp.name) / "offset.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def _updates(self, ids: list[int]) -> list[dict]:
        return [
            {"update_id": i,
             "message": {"text": "/grafik TMPOL 1d", "chat": {"id": -100123}}}
            for i in ids
        ]

    def test_processes_and_confirms_offset(self) -> None:
        """Son adimda offset onaylanmali; yoksa ayni komut tekrar islenir."""
        import os
        from unittest import mock

        from src import bot

        calls: list[dict] = []

        def fake_get_updates(offset=None, timeout=30):
            calls.append({"offset": offset})
            return self._updates([10, 11]) if offset is None else []

        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "-100123"}), \
                mock.patch.object(bot.tg, "_credentials", lambda: ("t", "-100123", "")), \
                mock.patch.object(bot.tg, "get_updates", fake_get_updates), \
                mock.patch.object(bot.tg, "send_message"), \
                mock.patch.object(bot, "_render_and_send"):
            handled = bot.poll_once()

        self.assertEqual(handled, 2)
        self.assertEqual(calls[-1]["offset"], 12)  # son update_id + 1

    def test_foreign_chat_is_skipped_but_still_confirmed(self) -> None:
        """Baska gruptan gelen komut islenmez ama onaylanir, yoksa sonsuza dek kalir."""
        import os
        from unittest import mock

        from src import bot

        confirmed: list[int | None] = []

        def fake_get_updates(offset=None, timeout=30):
            confirmed.append(offset)
            if offset is None:
                return [{"update_id": 5,
                         "message": {"text": "/grafik X", "chat": {"id": -999}}}]
            return []

        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "-100123"}), \
                mock.patch.object(bot.tg, "_credentials", lambda: ("t", "-100123", "")), \
                mock.patch.object(bot.tg, "get_updates", fake_get_updates), \
                mock.patch.object(bot, "_render_and_send") as render:
            handled = bot.poll_once()

        self.assertEqual(handled, 0)
        render.assert_not_called()
        self.assertEqual(confirmed[-1], 6)

    def test_empty_queue_does_nothing(self) -> None:
        from unittest import mock

        from src import bot

        with mock.patch.object(bot.tg, "_credentials", lambda: ("t", "c", "")), \
                mock.patch.object(bot.tg, "get_updates", lambda offset=None, timeout=30: []):
            self.assertEqual(bot.poll_once(), 0)

    def test_one_failing_command_does_not_stop_the_rest(self) -> None:
        import os
        from unittest import mock

        from src import bot

        def fake_get_updates(offset=None, timeout=30):
            return self._updates([1, 2, 3]) if offset is None else []

        attempts = {"n": 0}

        def flaky(message):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("veri gelmedi")

        with mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "-100123"}), \
                mock.patch.object(bot.tg, "_credentials", lambda: ("t", "-100123", "")), \
                mock.patch.object(bot.tg, "get_updates", fake_get_updates), \
                mock.patch.object(bot, "handle", flaky):
            handled = bot.poll_once()

        self.assertEqual(attempts["n"], 3)
        self.assertEqual(handled, 2)


class TestBotOffsetState(unittest.TestCase):
    """Offset diske yazilmazsa kosular arasinda komut kaybolur ya da tekrarlanir."""

    def test_roundtrip(self) -> None:
        from unittest import mock

        from src import bot

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "offset.json"
            with mock.patch.object(bot, "STATE_FILE", path):
                self.assertIsNone(bot.load_offset())
                bot.save_offset(42)
                self.assertEqual(bot.load_offset(), 42)

    def test_corrupt_file_starts_clean(self) -> None:
        from unittest import mock

        from src import bot

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "offset.json"
            path.write_text("bu json degil", encoding="utf-8")
            with mock.patch.object(bot, "STATE_FILE", path):
                self.assertIsNone(bot.load_offset())


class TestTimedRun(unittest.TestCase):
    """--minutes ile calisan dongu suresi dolunca cikmali."""

    def test_run_stops_at_deadline(self) -> None:
        from unittest import mock

        from src import bot

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bot, "STATE_FILE", Path(tmp) / "o.json"), \
                mock.patch.object(bot.tg, "_credentials", lambda: ("t", "c", "")), \
                mock.patch.object(bot.tg, "get_updates",
                                  lambda offset=None, timeout=25: []):
            handled = bot.run(minutes=0.0005, poll_timeout=0)  # ~30 ms
        self.assertEqual(handled, 0)

    def test_offset_saved_per_update(self) -> None:
        import os
        from unittest import mock

        from src import bot

        batches = [[
            {"update_id": 7,
             "message": {"text": "/grafik X 1d", "chat": {"id": -100123}}}
        ]]

        def fake_get_updates(offset=None, timeout=25):
            return batches.pop() if batches else []

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"TELEGRAM_CHAT_ID": "-100123"}), \
                mock.patch.object(bot, "STATE_FILE", Path(tmp) / "o.json"), \
                mock.patch.object(bot.tg, "_credentials", lambda: ("t", "-100123", "")), \
                mock.patch.object(bot.tg, "get_updates", fake_get_updates), \
                mock.patch.object(bot.tg, "send_message"), \
                mock.patch.object(bot, "_render_and_send"), \
                mock.patch.object(bot, "STATE_FILE", Path(tmp) / "o.json"):
            bot.run(minutes=0.004, poll_timeout=0)
            self.assertEqual(bot.load_offset(), 8)


class TestSelfRestart(unittest.TestCase):
    """Zincir: kosu bitince workflow yeniden tetiklenmeli."""

    def _env(self, **extra) -> dict:
        base = {"GITHUB_REPOSITORY": "kisi/depo", "GITHUB_REF_NAME": "main",
                "GH_PAT": "", "GITHUB_TOKEN": ""}
        base.update(extra)
        return base

    def test_dispatch_called_with_pat(self) -> None:
        import os
        from unittest import mock

        from src import bot_runner

        captured = {}

        class R:
            status_code = 204
            text = ""

        def fake_post(url, headers=None, json=None, timeout=None):
            captured.update(url=url, headers=headers, json=json)
            return R()

        with mock.patch.dict(os.environ, self._env(GH_PAT="pat123")), \
                mock.patch.object(bot_runner.requests, "post", fake_post):
            self.assertTrue(bot_runner.restart_self())

        self.assertIn("kisi/depo", captured["url"])
        self.assertIn("chart-bot.yml", captured["url"])
        self.assertEqual(captured["json"], {"ref": "main"})
        self.assertIn("pat123", captured["headers"]["Authorization"])

    def test_github_token_preferred_over_pat(self) -> None:
        import os
        from unittest import mock

        from src import bot_runner

        with mock.patch.dict(os.environ, self._env(GH_PAT="pat", GITHUB_TOKEN="tok")):
            self.assertEqual(bot_runner._restart_tokens()[0], ("tok", "GITHUB_TOKEN"))

    def test_missing_token_is_reported_not_raised(self) -> None:
        import os
        from unittest import mock

        from src import bot_runner

        with mock.patch.dict(os.environ, self._env()):
            self.assertFalse(bot_runner.restart_self())

    def test_http_error_returns_false(self) -> None:
        import os
        from unittest import mock

        from src import bot_runner

        class R:
            status_code = 403
            text = "Resource not accessible"

        with mock.patch.dict(os.environ, self._env(GITHUB_TOKEN="tok")), \
                mock.patch.object(bot_runner.requests, "post",
                                  lambda *a, **k: R()):
            self.assertFalse(bot_runner.restart_self())

    def test_self_restart_can_be_disabled(self) -> None:
        import os
        from unittest import mock

        from src import bot_runner

        with mock.patch.dict(os.environ, {"BOT_SELF_RESTART": "0",
                                          "BOT_RUN_MINUTES": "0.0005"}), \
                mock.patch.object(bot_runner.bot, "run", lambda minutes=None: 0), \
                mock.patch.object(bot_runner, "restart_self") as restart:
            bot_runner.main()
            restart.assert_not_called()


class TestTelegramConfigCheck(unittest.TestCase):
    """Yapilandirma eksikse IS BASLAMADAN hata verilmeli.

    Sonda kontrol edilirse dort periyodun grafikleri uretildikten sonra hata
    verilir; Actions'ta dakikalarca suren kosu bosa gider.
    """

    def test_missing_config_fails_before_any_rendering(self) -> None:
        import os
        from unittest import mock

        from src import cli

        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "",
                                          "TELEGRAM_CHAT_ID": ""}), \
                mock.patch.object(cli, "_build_one") as build:
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["--symbol", "ASELS", "--telegram"])
            build.assert_not_called()

        message = str(ctx.exception)
        self.assertIn("TELEGRAM_BOT_TOKEN", message)
        self.assertIn("secret", message.lower())

    def test_error_names_only_the_missing_variable(self) -> None:
        import os
        from unittest import mock

        from src.telegram import TelegramError, _credentials

        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc",
                                          "TELEGRAM_CHAT_ID": ""}):
            with self.assertRaises(TelegramError) as ctx:
                _credentials()
        message = str(ctx.exception)
        self.assertIn("TELEGRAM_CHAT_ID", message)
        self.assertNotIn("TELEGRAM_BOT_TOKEN,", message)

    def test_no_check_when_telegram_not_requested(self) -> None:
        """--telegram yoksa yapilandirma aranmamali."""
        import os
        from unittest import mock

        from src import cli

        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "",
                                          "TELEGRAM_CHAT_ID": ""}), \
                mock.patch.object(cli, "_build_one",
                                  side_effect=RuntimeError("veri yok")):
            with self.assertRaises(RuntimeError):
                cli.main(["--symbol", "ASELS", "--no-html"])
