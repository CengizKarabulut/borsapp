import unittest

from src.plain_language import build_plain_summary

JARGON = [
    "RVOL", "ATR", "VAH", "VAL", "POC", "EMA", "MACD", "RSI", "ADX", "SMI",
    "Bollinger", "AVWAP", "divergence", "uyumsuzluk", "momentum", "percentile",
]


def summary(**overrides):
    payload = {
        "symbol": "THYAO",
        "price": 300.5,
        "change_pct": -0.17,
        "setup_context": {
            "setup": {"name": "Sıkışma / karar bölgesi", "bias": "iki yönlü"},
            "duration": {"squeeze_bars": 7},
            "participation_reading": {"rvol_1": 0.56},
        },
        "scenario": {"strengthen": ["325.50 üzerinde kapanış: yukarı çözülme", "295.25 altında kapanış: aşağı çözülme"]},
        "clarity": {"state": "Düşük"},
        "bar_state": {"is_live": False},
    }
    payload.update(overrides)
    return build_plain_summary(**payload)


class PlainLanguageTests(unittest.TestCase):
    def test_summary_avoids_technical_jargon(self) -> None:
        text = summary()["text"]
        for term in JARGON:
            self.assertNotIn(term.casefold(), text.casefold(), f"'{term}' sade özette geçmemeli")

    def test_summary_states_price_and_both_thresholds(self) -> None:
        text = summary()["text"]
        self.assertIn("300.50", text)
        self.assertIn("325.50", text)
        self.assertIn("295.25", text)
        self.assertIn("olursa yukarı", text)
        self.assertIn("olursa aşağı", text)

    def test_squeeze_duration_is_expressed_in_days(self) -> None:
        self.assertIn("7 işlem günüdür", summary()["text"])

    def test_low_volume_is_framed_as_expected_inside_squeeze(self) -> None:
        text = summary()["text"]
        self.assertIn("beklenen bir durum", text)

    def test_low_volume_is_a_warning_outside_squeeze(self) -> None:
        text = summary(
            setup_context={
                "setup": {"name": "Trend devamı", "bias": "aşağı"},
                "duration": {"squeeze_bars": 0},
                "participation_reading": {"rvol_1": 0.56},
            }
        )["text"]
        self.assertIn("katılım zayıf", text)
        self.assertNotIn("beklenen bir durum", text)

    def test_failed_breakdown_is_explained_in_everyday_words(self) -> None:
        text = summary(
            setup_context={
                "setup": {"name": "Destekte reddedilme / başarısız aşağı kırılım", "bias": "iki yönlü"},
                "duration": {"squeeze_bars": 0},
                "participation_reading": {"rvol_1": 1.0},
            }
        )["text"]
        self.assertIn("aşağı kırmayı denedi ama başaramadı", text)

    def test_live_bar_warning_is_added(self) -> None:
        text = summary(bar_state={"is_live": True})["text"]
        self.assertIn("henüz kapanmadı", text)

    def test_disclaimer_always_present(self) -> None:
        self.assertIn("tavsiyesi değildir", summary()["text"])

    def test_unknown_setup_falls_back_without_crashing(self) -> None:
        text = summary(
            setup_context={
                "setup": {"name": "Bilinmeyen kurulum", "bias": "iki yönlü"},
                "duration": {},
                "participation_reading": {},
            }
        )["text"]
        self.assertIn("klasik bir kalıba tam oturmuyor", text)


class ScanLineTests(unittest.TestCase):
    """Tarama listesi teknik analiz bilmeyen biri için de okunabilir olmalı."""

    def _item(self, **overrides):
        base = {
            "setup": "Destekte reddedilme / başarısız aşağı kırılım",
            "rvol": 2.49,
            "excess_return_20": -5.5,
            "active_levels": {"lower": 89.10, "reference_close": 96.40, "upper": 103.20},
            "matched_intervals": ["1d", "1wk"],
        }
        base.update(overrides)
        return base

    def test_line_avoids_technical_jargon(self) -> None:
        from src.plain_language import scan_line_plain

        text = scan_line_plain(self._item())
        for term in ("RVOL", "BB", "ATR", "EMA", "VAL", "VAH", "POC", "XU100"):
            self.assertNotIn(term, text)

    def test_line_states_the_thresholds(self) -> None:
        from src.plain_language import scan_line_plain

        text = scan_line_plain(self._item())
        self.assertIn("103.20", text)
        self.assertIn("89.10", text)
        self.assertIn("96.40", text)
        self.assertIn("Teyitli referans kapanış", text)

    def test_high_volume_is_described_plainly(self) -> None:
        from src.plain_language import scan_line_plain

        self.assertIn("çok yoğun ilgi", scan_line_plain(self._item(rvol=4.2)))

    def test_low_volume_is_described_plainly(self) -> None:
        from src.plain_language import scan_line_plain

        self.assertIn("ilgi sınırlı", scan_line_plain(self._item(rvol=0.5)))

    def test_relative_strength_is_described_plainly(self) -> None:
        from src.plain_language import scan_line_plain

        self.assertIn("endeksten belirgin şekilde iyi", scan_line_plain(self._item(excess_return_20=8.0)))
        self.assertIn("endeksin gerisinde", scan_line_plain(self._item(excess_return_20=-8.0)))

    def test_multi_timeframe_is_mentioned(self) -> None:
        from src.plain_language import scan_line_plain

        self.assertIn("Birden fazla zaman diliminde", scan_line_plain(self._item()))
        self.assertNotIn("Birden fazla", scan_line_plain(self._item(matched_intervals=["1d"])))

    def test_missing_levels_do_not_break_the_line(self) -> None:
        from src.plain_language import scan_line_plain

        text = scan_line_plain(self._item(active_levels={}))
        self.assertTrue(text)
        self.assertNotIn("Teyitli referans kapanış", text)

    def test_unknown_setup_has_a_fallback(self) -> None:
        from src.plain_language import scan_line_plain

        self.assertIn("klasik bir kalıba tam oturmuyor", scan_line_plain(self._item(setup="Bilinmeyen")))


class ProjectedVolumeTests(unittest.TestCase):
    """Yarım barda gösterilen RVOL bir projeksiyondur; olgu gibi sunulmamalı."""

    def test_forming_bar_states_both_values(self) -> None:
        from src.plain_language import scan_line_plain

        text = scan_line_plain({
            "setup": "Sıkışma / karar bölgesi", "rvol": 6.91, "rvol_observed": 2.02,
            "bar_fraction": 0.29, "excess_return_20": 0.0, "levels": {}, "matched_intervals": ["1d"],
        })
        self.assertIn("şu ana kadar normalin 2.0 katı", text)
        self.assertIn("bu hızla giderse", text)
        self.assertIn("6.9 katına", text)

    def test_completed_bar_states_a_single_value(self) -> None:
        from src.plain_language import scan_line_plain

        text = scan_line_plain({
            "setup": "Sıkışma / karar bölgesi", "rvol": 3.4, "bar_fraction": 1.0,
            "excess_return_20": 0.0, "levels": {}, "matched_intervals": ["1d"],
        })
        self.assertIn("normalin 3.4 katı", text)
        self.assertNotIn("bu hızla giderse", text)

    def test_missing_observed_value_falls_back(self) -> None:
        from src.plain_language import scan_line_plain

        text = scan_line_plain({
            "setup": "Trend devamı", "rvol": 2.0, "bar_fraction": 0.5,
            "excess_return_20": 0.0, "levels": {}, "matched_intervals": ["1d"],
        })
        self.assertIn("normalin 2.0 katı", text)


if __name__ == "__main__":
    unittest.main()
