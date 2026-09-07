import tempfile
import unittest
from pathlib import Path

from src.analyst_card import _blocks, render_analyst_card, render_analyst_cards

STATUS = {
    "symbol": "THYAO",
    "price": 300.5,
    "change_pct": -0.17,
    "timestamp": "2026-08-18T09:00:00+03:00",
    "data_provider": "borsapy/TradingView",
    "bar_state": {"label": "TEYİTLİ", "is_live": False},
    "technical_commentary": {
        "setup": {"name": "Sıkışma / karar bölgesi", "bias": "iki yönlü", "tone": "neutral", "description": "Dar aralıkta denge."},
        "duration": {"summary": "7 bardır dar bant bölgesinde"},
        "analyst_note": "Birinci paragraf.\n\nİkinci paragraf.",
        "market_story": "Hikâye şöyle: Fiyat karar alanında ve yön henüz seçilmedi.",
        "candle_story": "Son mumda Doji görüldü; tek başına yön kanıtı değildir.",
        "general_interpretation": "Net sonuç: 325,50 üstü yukarı, 295,25 altı aşağı teyittir.",
        "indicator_schemas": [
            {
                "name": "1 · Bollinger / MACD / SMI / OBV",
                "state": "Karışık",
                "plain": "Hız ve hacim aynı yönde değil.",
                "guide": "Genel okuma: fiyat, hız ve hacim birlikte değerlendirilir.",
                "stock_comment": "Bu hissede hız toparlanırken hacim henüz eşlik etmiyor.",
                "reading": "Fiyat 300,50; MACD -0,20; OBV ortalama altında.",
                "confirmation": "Teyit için fiyat ve hacim aynı yönde kapanmalı.",
                "risk": "Hacimsiz hareket yanıltıcı olabilir.",
                "tone": "warning",
            },
            {"name": "2 · Ichimoku / RSI / CCI / ATR", "state": "Aşağı baskı", "plain": "Ana yön satıcıları destekliyor.", "tone": "negative"},
        ],
        "reconciliation": "Kanıtlar iki yöne dağılmış.",
        "plain_summary": {"text": "THYAO 300,50 seviyesinde. Fiyat dar bir aralıkta."},
        "supporting_evidence": [{"family": "Yapı", "state": "HH / HL"}],
        "counter_evidence": [{"family": "Momentum", "state": "Negatif"}],
        "clarity": {"state": "Düşük", "tone": "warning", "reason": "Kanıtlar dağılmış."},
        "levels": {"clusters": [{"low": 297.56, "high": 299.5, "side": "destek", "strength": "Orta", "members": ["BB Alt", "VAL"]}]},
        "scenario_map": {
            "strengthen": ["325.50 üzerinde kapanış: yukarı çözülme", "295.25 altında kapanış: aşağı çözülme"],
            "weaken": ["Aralık içinde kalınması"],
            "neutral": ["Sıkışmanın sürmesi"],
            "labels": {"strengthen": "Yukarı/aşağı çözülme koşulları", "weaken": "Kurulumu geçersiz kılacak", "neutral": "Durumu koruyacak"},
        },
        "changes": ["Yeni olay: SMI ↓ -40."],
    },
}


class AnalystCardTests(unittest.TestCase):
    def test_card_png_is_created_with_content_driven_height(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = render_analyst_card(STATUS, Path(directory) / "card.png")
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 10_000)

    def test_longer_note_produces_taller_card(self) -> None:
        long_status = {**STATUS, "technical_commentary": {**STATUS["technical_commentary"]}}
        long_status["technical_commentary"]["market_story"] = "Uzun paragraf. " * 200
        with tempfile.TemporaryDirectory() as directory:
            short = render_analyst_card(STATUS, Path(directory) / "short.png")
            tall = render_analyst_card(long_status, Path(directory) / "tall.png")
            self.assertGreater(tall.stat().st_size, short.stat().st_size)

    def test_two_sided_thresholds_are_coloured_by_direction(self) -> None:
        blocks = _blocks(STATUS)
        upward = [block for block in blocks if "yukarı çözülme" in block.text]
        downward = [block for block in blocks if "aşağı çözülme" in block.text]
        self.assertTrue(upward and downward)
        self.assertNotEqual(upward[0].colour, downward[0].colour)

    def test_card_includes_plain_summary_and_setup(self) -> None:
        texts = " ".join(block.text for block in _blocks(STATUS))
        self.assertIn("PİYASANIN HİKÂYESİ", texts)
        self.assertIn("Sıkışma / karar bölgesi", texts)
        self.assertIn("NET SONUÇ", texts)
        self.assertIn("SON İKİ MUM NE DİYOR?", texts)

    def test_missing_sections_do_not_break_rendering(self) -> None:
        minimal = {"symbol": "X", "price": 1.0, "change_pct": 0.0, "technical_commentary": {}}
        with tempfile.TemporaryDirectory() as directory:
            path = render_analyst_card(minimal, Path(directory) / "minimal.png")
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()


class CardWrappingTests(unittest.TestCase):
    def test_bold_text_wraps_earlier_than_regular_text(self) -> None:
        from src.analyst_card import _wrap

        text = "Dirençte reddedilme / başarısız yukarı kırılım • eğilim: iki yönlü uzun başlık"
        regular = _wrap(text, 18, 9.0, "normal")
        bold = _wrap(text, 18, 9.0, "bold")
        self.assertGreaterEqual(len(bold), len(regular))

    def test_raw_analyst_note_is_replaced_by_structured_sections(self) -> None:
        texts = [block.text for block in _blocks(STATUS)]
        self.assertNotIn("Birinci paragraf.", texts)
        self.assertIn("DÖRT GÖSTERGE GRUBU", texts)

    def test_indicator_group_shows_guide_and_stock_specific_reading(self) -> None:
        texts = " ".join(block.text for block in _blocks(STATUS))
        self.assertIn("NASIL OKUNUR?", texts)
        self.assertIn("BU HİSSEDE NE SÖYLÜYOR?", texts)
        self.assertIn("GÖSTERGE DEĞERLERİ", texts)
        self.assertIn("TEYİT", texts)
        self.assertIn("RİSK", texts)


class CardPagingTests(unittest.TestCase):
    def test_cards_are_produced_as_a_balanced_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = render_analyst_cards(STATUS, Path(directory))
            self.assertGreaterEqual(len(paths), 1)
            for path in paths:
                self.assertTrue(path.exists())
                self.assertGreater(path.stat().st_size, 5_000)

    def test_combined_card_is_not_smaller_than_a_single_page(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            combined = render_analyst_card(STATUS, Path(directory) / "combined.png")
            paths = render_analyst_cards(STATUS, Path(directory))
            self.assertGreaterEqual(combined.stat().st_size, min(path.stat().st_size for path in paths))

    def test_bar_state_is_expressed_in_plain_words(self) -> None:
        from src.plain_language import bar_state_plain

        self.assertIn("Gün kapandı", bar_state_plain({"label": "TEYİTLİ", "is_live": False}))
        self.assertIn("Gün sürüyor", bar_state_plain({"label": "CANLI", "is_live": True}))


class CardBalanceTests(unittest.TestCase):
    def test_evidence_appears_only_on_the_first_card(self) -> None:
        from src.analyst_card import CARD_PAGES

        commentary = STATUS["technical_commentary"]
        overview = " ".join(block.text for block in CARD_PAGES[0][1](commentary))
        detail = " ".join(block.text for block in CARD_PAGES[1][1](commentary))
        self.assertIn("KANIT DENGESİ", overview)
        self.assertNotIn("KANIT DENGESİ", detail)

    def test_levels_and_scenarios_appear_on_the_second_card(self) -> None:
        from src.analyst_card import CARD_PAGES

        detail = " ".join(block.text for block in CARD_PAGES[1][1](STATUS["technical_commentary"]))
        self.assertIn("TEKNİK YOĞUNLAŞMA BÖLGELERİ", detail)
        self.assertIn("yukarı çözülme", detail)


class StandardizeTests(unittest.TestCase):
    def test_pages_keep_content_driven_heights(self) -> None:
        from PIL import Image

        from src.analyst_card import standardize_pages

        with tempfile.TemporaryDirectory() as directory:
            paths = []
            for index, height in enumerate((900, 1500, 1200), start=1):
                path = Path(directory) / f"page_{index}.png"
                Image.new("RGB", (1200, height), "#0f172a").save(path)
                paths.append(path)
            standardize_pages(paths)
            sizes = [Image.open(path).size for path in paths]
            self.assertEqual(sizes, [(1200, 900), (1200, 1500), (1200, 1200)])

    def test_content_is_preserved_without_height_padding(self) -> None:
        from PIL import Image

        from src.analyst_card import standardize_pages

        with tempfile.TemporaryDirectory() as directory:
            short = Path(directory) / "short.png"
            tall = Path(directory) / "tall.png"
            image = Image.new("RGB", (1200, 600), "#ffffff")
            image.save(short)
            Image.new("RGB", (1200, 1400), "#0f172a").save(tall)
            standardize_pages([short, tall])
            padded = Image.open(short)
            self.assertEqual(padded.size, (1200, 600))
            self.assertEqual(padded.getpixel((10, 10)), (255, 255, 255))

    def test_empty_input_is_handled(self) -> None:
        from src.analyst_card import standardize_pages

        self.assertEqual(standardize_pages([]), [])

    def test_cards_are_balanced_into_one_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = render_analyst_cards(STATUS, Path(directory))
            self.assertGreaterEqual(len(paths), 1)
            heights = [Path(path).stat().st_size for path in paths]
            self.assertTrue(all(size > 5_000 for size in heights))
