from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from src.fundamental_analysis import Factor, FundamentalReport
from src.research_card import render_research_card
from src.research_engine import (
    LevelZone,
    ResearchDimension,
    ResearchReport,
    RiskItem,
    _financial_analysis,
    _level_zones,
    _pivots,
    _prepare_prices,
)


PERIODS = ["2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]


def statement(rows: dict[str, list[float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, index=PERIODS).T


class ResearchEngineTests(unittest.TestCase):
    def fundamental(self) -> FundamentalReport:
        return FundamentalReport(
            symbol="TEST",
            company_name="Test Sanayi",
            price=120.0,
            sector="Industrials",
            profile="GENERIC",
            overall_score=3.8,
            coverage=0.9,
            factors=(Factor("Kârlılık", 4.0, 1.0, ""),),
            positives=(),
            risks=(),
            metrics={"roe": 24.0, "roa": 9.0},
            note="test",
        )

    def test_improving_balance_and_cash_quality_are_recognised(self) -> None:
        balance = statement(
            {
                "Toplam Varlıklar": [1000, 1040, 1080, 1120, 1180, 1240, 1300, 1380],
                "Dönen Varlıklar": [400, 420, 440, 460, 500, 540, 580, 620],
                "Kısa Vadeli Yükümlülükler": [300, 305, 310, 315, 320, 325, 330, 335],
                "Özkaynaklar": [450, 470, 490, 510, 550, 590, 630, 680],
                "Nakit ve Nakit Benzerleri": [90, 100, 110, 120, 145, 165, 190, 220],
                "Kısa Vadeli Borçlanmalar": [170, 165, 160, 155, 145, 135, 125, 115],
                "Uzun Vadeli Borçlanmalar": [260, 250, 240, 230, 215, 200, 185, 170],
                "Ticari Alacaklar": [160, 165, 170, 175, 180, 190, 200, 210],
                "Stoklar": [120, 122, 124, 126, 128, 130, 132, 134],
            }
        )
        income = statement(
            {
                "Hasılat": [200, 210, 220, 230, 250, 265, 280, 300],
                "Brüt Kar": [60, 64, 68, 72, 82, 88, 95, 104],
                "Esas Faaliyet Karı": [35, 38, 41, 44, 52, 57, 62, 69],
                "FAVÖK": [42, 45, 48, 51, 60, 65, 71, 78],
                "Net Dönem Karı": [25, 27, 29, 31, 36, 39, 43, 48],
                "Finansman Giderleri": [-9, -9, -8, -8, -7, -7, -6, -6],
            }
        )
        cashflow = statement(
            {
                "İşletme Faaliyetlerinden Nakit Akışları": [27, 29, 31, 34, 40, 43, 47, 53],
                "Maddi Duran Varlık Alımları": [-8, -8, -9, -9, -10, -10, -11, -11],
            }
        )
        result = _financial_analysis(self.fundamental(), balance, income, cashflow)
        self.assertGreater(result["balance_score"], 60)
        self.assertGreater(result["earnings_quality_score"], 60)
        self.assertEqual(result["debt_direction"], "AZALIYOR")
        self.assertGreater(result["metrics"]["cfo_net_income"], 0.8)

    def test_actionable_support_is_always_below_price_and_resistance_above(self) -> None:
        index = pd.date_range("2025-01-02", periods=270, freq="B")
        trend = np.linspace(70.0, 120.0, len(index))
        wave = np.sin(np.arange(len(index)) / 5.0) * 4.0
        close = trend + wave
        frame = pd.DataFrame(
            {
                "Open": close - 0.4,
                "High": close + 1.3,
                "Low": close - 1.3,
                "Close": close,
                "Volume": np.linspace(1_000_000, 2_000_000, len(index)),
            },
            index=index,
        )
        data = _prepare_prices(frame).dropna(subset=["ATR"])
        pivots = _pivots(data)
        supports, resistances = _level_zones(data, pivots)
        price = float(data["Close"].iloc[-1])
        self.assertTrue(all(zone.midpoint < price for zone in supports))
        self.assertTrue(all(zone.midpoint > price for zone in resistances))
        self.assertTrue(all(zone.status != "TARİHSEL / UZAK SEVİYE" for zone in (*supports, *resistances)))

    def test_research_card_renders(self) -> None:
        fundamental = self.fundamental()
        report = ResearchReport(
            symbol="TEST",
            company_name="Test Sanayi",
            price=120.0,
            sector="Industrials",
            profile="GENERIC",
            research_score=72.0,
            coverage=0.82,
            dimensions=(
                ResearchDimension("Şirket Kalitesi", 76.0, 0.9, "GÜÇLÜ", "Kârlılık ve nakit üretimi güçlü."),
                ResearchDimension("Bilanço Trendi", 71.0, 0.8, "İYİLEŞİYOR", "Net borç düşüyor."),
                ResearchDimension("Kâr Kalitesi", 68.0, 0.8, "ORTA", "CFO/net kâr 0.95x."),
                ResearchDimension("Değerleme", 63.0, 0.7, "MAKUL", "Sektör medyanına yakın."),
                ResearchDimension("Teknik Yapı", 82.0, 0.9, "POZİTİF", "HH/HL yapısı korunuyor."),
            ),
            main_risk=RiskItem("Değerleme hassasiyeti", 61.0, "Büyüme yavaşlarsa çarpan baskısı oluşabilir."),
            risks=(RiskItem("Değerleme hassasiyeti", 61.0, "test"),),
            supports=(LevelZone("destek", 112.0, 113.0, 112.5, 78.0, "AKTİF DESTEK", 1.2, 3, 8, ("HL", "EMA21")),),
            resistances=(LevelZone("direnç", 126.0, 127.0, 126.5, 72.0, "AKTİF DİRENÇ", 1.5, 2, 12, ("HH", "Fib61.8")),),
            technical={"label": "POZİTİF"},
            financial={"balance_label": "İYİLEŞİYOR", "earnings_quality_label": "ORTA", "debt_direction": "AZALIYOR"},
            valuation={"scope": "Industrials sektörü"},
            fundamental=fundamental,
            note="Eksik veri puanlanmaz.",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = render_research_card(report, Path(directory) / "research.png")
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 10_000)


if __name__ == "__main__":
    unittest.main()
