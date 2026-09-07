import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from src.stock_dashboard import (
    MA_PERIODS,
    MA_TABLE_PERIODS,
    ScanConfig,
    build_status,
    calculate_indicators,
    download_prices,
    effective_download_period,
    normalize_symbol,
    rsi,
    validate_price_data,
)


def synthetic_prices(rows: int = 500) -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=rows, freq="D")
    trend = np.linspace(20.0, 120.0, rows)
    wave = np.sin(np.arange(rows) / 8.0) * 2.0
    close = trend + wave
    return pd.DataFrame(
        {
            "Open": close - 0.4,
            "High": close + 1.1,
            "Low": close - 1.0,
            "Close": close,
            "Volume": np.linspace(1_000_000, 2_000_000, rows),
        },
        index=index,
    )


class IndicatorTests(unittest.TestCase):
    def test_bist_symbol_suffix(self) -> None:
        self.assertEqual(normalize_symbol("thyao", "BIST"), "THYAO.IS")
        self.assertEqual(normalize_symbol("THYAO.IS", "BIST"), "THYAO.IS")
        self.assertEqual(normalize_symbol("aapl", "US"), "AAPL")

    def test_warmup_period_is_separate_from_requested_period(self) -> None:
        self.assertEqual(effective_download_period("6mo", "2y"), "2y")
        self.assertEqual(effective_download_period("5y", "2y"), "5y")

    def test_auto_market_prefers_verified_bist_symbol(self) -> None:
        expected = ("THYAO", synthetic_prices())
        with (
            patch("src.stock_dashboard.download_borsapy", return_value=expected) as borsapy_download,
            patch("src.stock_dashboard.download_yfinance") as yahoo_download,
        ):
            result = download_prices(ScanConfig("THYAO", market="AUTO", provider="AUTO"))
        self.assertEqual(result[0], "THYAO")
        self.assertEqual(borsapy_download.call_args.args[0].market, "BIST")
        yahoo_download.assert_not_called()

    def test_auto_market_falls_back_from_bist_candidates_to_us(self) -> None:
        def yahoo_side_effect(config):
            if config.market == "BIST":
                raise RuntimeError("AAPL.IS bulunamadı")
            return "AAPL", synthetic_prices()

        with (
            patch("src.stock_dashboard.download_borsapy", side_effect=RuntimeError("BIST sembolü yok")),
            patch("src.stock_dashboard.download_yfinance", side_effect=yahoo_side_effect) as yahoo_download,
        ):
            result = download_prices(ScanConfig("AAPL", market="AUTO", provider="AUTO"))
        self.assertEqual(result[0], "AAPL")
        self.assertEqual([call.args[0].market for call in yahoo_download.call_args_list], ["BIST", "US"])

    def test_rsi_flat_rising_and_falling_edge_cases(self) -> None:
        flat = pd.Series([10.0] * 40)
        rising = pd.Series(np.arange(1.0, 41.0))
        falling = pd.Series(np.arange(40.0, 0.0, -1.0))
        self.assertEqual(rsi(flat).iloc[-1], 50.0)
        self.assertEqual(rsi(rising).iloc[-1], 100.0)
        self.assertEqual(rsi(falling).iloc[-1], 0.0)

    def test_mfi_flat_zero_flow_is_neutral(self) -> None:
        frame = synthetic_prices()
        frame[["Open", "High", "Low", "Close"]] = 100.0
        self.assertEqual(calculate_indicators(frame)["MFI"].iloc[-1], 50.0)

    def test_price_validation_preserves_provider(self) -> None:
        data = validate_price_data(synthetic_prices(), "TEST", "borsapy/TradingView")
        self.assertEqual(data.attrs["provider"], "borsapy/TradingView")
        with self.assertRaisesRegex(RuntimeError, "en az 120 bar"):
            validate_price_data(synthetic_prices(100), "TEST", "test")

    def test_all_ma_periods_are_calculated(self) -> None:
        result = calculate_indicators(synthetic_prices())
        for length in MA_PERIODS:
            self.assertIn(f"SMA_{length}", result.columns)
            self.assertIn(f"EMA_{length}", result.columns)
            self.assertTrue(np.isfinite(result[f"SMA_{length}"].iloc[-1]))
            self.assertTrue(np.isfinite(result[f"EMA_{length}"].iloc[-1]))

    def test_status_contains_thirteen_sma_ema_wma_rows(self) -> None:
        result = calculate_indicators(synthetic_prices())
        status = build_status(result, ScanConfig("TEST", "US"), "TEST")
        self.assertEqual(len(status["ma"]), 13)
        self.assertEqual([item["period"] for item in status["ma"]], MA_TABLE_PERIODS)
        self.assertTrue(all("wma" in item for item in status["ma"]))
        self.assertIn("technical_commentary", status)
        self.assertEqual(len(status["technical_commentary"]["visual_rows"]), 12)
        self.assertEqual(status["candlestick_summary"]["window"], 2)
        self.assertTrue(status["candlestick_summary"]["story"])
        self.assertIn("Son 2 mumun hikâyesi", [item[0] for item in status["trend_volatility_volume"]])

    def test_core_indicators_are_finite(self) -> None:
        row = calculate_indicators(synthetic_prices()).iloc[-1]
        for column in ["RSI", "MACD", "MACD_SIGNAL", "SMI", "SMI_EMA", "ATR", "ADX", "MFI", "CCI", "OBV"]:
            self.assertTrue(np.isfinite(row[column]), column)


if __name__ == "__main__":
    unittest.main()



class TradingViewParityTests(unittest.TestCase):
    def test_cci_matches_tradingview_formula(self) -> None:
        import numpy as np

        from src.stock_dashboard import calculate_indicators

        rng = np.random.default_rng(5)
        bars = 200
        index = pd.bdate_range("2024-01-01", periods=bars)
        close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, bars)))
        frame = pd.DataFrame(
            {
                "Open": close,
                "High": close * 1.01,
                "Low": close * 0.99,
                "Close": close,
                "Volume": np.full(bars, 1_000_000.0),
            },
            index=index,
        )
        result = calculate_indicators(frame)
        source = (frame["High"] + frame["Low"] + frame["Close"]) / 3
        average = source.rolling(20).mean()
        deviation = source.rolling(20).apply(lambda values: np.mean(np.abs(values - values.mean())), raw=True)
        expected = (source - average) / (0.015 * deviation)
        difference = (result["CCI"] - expected).abs().max()
        self.assertLess(difference, 1e-9)

    def test_cci_smoothing_uses_tradingview_default_length(self) -> None:
        import numpy as np

        from src.stock_dashboard import calculate_indicators

        bars = 120
        index = pd.bdate_range("2024-01-01", periods=bars)
        close = np.linspace(100, 130, bars)
        frame = pd.DataFrame(
            {"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": np.full(bars, 1_000.0)},
            index=index,
        )
        result = calculate_indicators(frame)
        expected = result["CCI"].rolling(14).mean()
        self.assertAlmostEqual(float(result["CCI_MA"].iloc[-1]), float(expected.iloc[-1]), places=9)


class ShortHistoryTests(unittest.TestCase):
    def test_recently_listed_symbol_produces_a_report(self) -> None:
        import numpy as np

        from src.intervals import resolve
        from src.stock_dashboard import (
            ScanConfig,
            build_status,
            calculate_indicators,
            validate_price_data,
        )

        rng = np.random.default_rng(6)
        bars = 145
        index = pd.bdate_range("2026-01-05", periods=bars)
        close = 50 * np.exp(np.cumsum(rng.normal(0, 0.02, bars)))
        frame = pd.DataFrame(
            {"Open": close, "High": close * 1.02, "Low": close * 0.98, "Close": close, "Volume": rng.lognormal(15, 0.4, bars)},
            index=index,
        )
        validated = validate_price_data(frame, "ZGYO", "test", resolve("1d"))
        self.assertTrue(validated.attrs["short_history"])
        status = build_status(calculate_indicators(validated, "1d"), ScanConfig(ticker="ZGYO"), "ZGYO")
        self.assertTrue(status["short_history"])
        self.assertEqual(status["bar_count"], bars)
        self.assertEqual(len(status["ma"]), 13, "kullanıcının 13 periyodu tabloda kalmalı")
        unavailable = [item for item in status["ma"] if not item.get("available")]
        self.assertEqual([item["period"] for item in unavailable], [144, 200, 233])
        self.assertIn("Yetersiz veri", unavailable[0]["sma_relation"])
        self.assertIn("238 bar gerekir", next(item["sma_relation"] for item in unavailable if item["period"] == 233))

    def test_short_history_is_disclosed_in_plain_summary_and_limitations(self) -> None:
        import numpy as np

        from src.intervals import resolve
        from src.stock_dashboard import (
            ScanConfig,
            build_status,
            calculate_indicators,
            validate_price_data,
        )

        rng = np.random.default_rng(9)
        bars = 140
        index = pd.bdate_range("2026-01-05", periods=bars)
        close = 20 * np.exp(np.cumsum(rng.normal(0, 0.02, bars)))
        frame = pd.DataFrame(
            {"Open": close, "High": close * 1.02, "Low": close * 0.98, "Close": close, "Volume": rng.lognormal(15, 0.4, bars)},
            index=index,
        )
        validated = validate_price_data(frame, "YENI", "test", resolve("1d"))
        commentary = build_status(calculate_indicators(validated, "1d"), ScanConfig(ticker="YENI"), "YENI")["technical_commentary"]
        self.assertIn("işlem geçmişi kısa", commentary["plain_summary"]["text"])
        note = next(item for item in commentary["limitations"] if "geçmişi kısa" in item)
        self.assertIn("ikame edilmedi", note)
        self.assertIn("233", note)

    def test_long_history_carries_no_short_history_flag(self) -> None:
        from src.intervals import resolve
        from src.stock_dashboard import validate_price_data

        validated = validate_price_data(synthetic_prices(), "UZUN", "test", resolve("1d"))
        self.assertFalse(validated.attrs["short_history"])
