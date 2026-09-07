import unittest

from src.valuation_policy import build_valuation_policy

PEER = {
    "score": 55.0,
    "coverage": 0.75,
    "scope": "Finance sektörü",
    "metrics": {"pb": {"value": 1.2, "percentile": 50.0}},
}


class ValuationPolicyTests(unittest.TestCase):
    def _by_model(self, report):
        return {item["model"]: item for item in report["models"]}

    def test_gyo_uses_nav_primary_and_does_not_fabricate_it(self) -> None:
        report = build_valuation_policy(
            "GYO",
            "Real Estate",
            {"cfo_net_income": None, "fcf_margin": None},
            PEER,
            20.0,
        )
        models = self._by_model(report)
        self.assertEqual(report["primary_model"], "NAD / NAV")
        self.assertEqual(models["NAD / NAV"]["status"], "VERİ EKSİK")
        self.assertEqual(models["F/K"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["FD/FAVÖK"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["EPV / Kazanç Gücü"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["Temettü İskonto"]["status"], "VERİ EKSİK")
        self.assertEqual(models["Altman Z"]["status"], "UYGUN DEĞİL")
        self.assertEqual(report["computed_values"], {})

    def test_gyo_keeps_equity_models_as_support_without_inventing_inputs(self) -> None:
        report = build_valuation_policy(
            "GYO",
            "Gayrimenkul Yatırım Ortaklığı",
            {"roe": 39.0, "equity": 4_000_000.0, "cfo_net_income": 0.1, "fcf_margin": -2.0},
            PEER,
            38.72,
        )
        models = self._by_model(report)
        self.assertEqual(models["Haklı PD/DD"]["role"], "destek")
        self.assertEqual(models["Residual Income"]["role"], "destek")
        self.assertEqual(models["Haklı PD/DD"]["status"], "VERİ EKSİK")
        self.assertEqual(models["Residual Income"]["status"], "VERİ EKSİK")
        self.assertIsNone(models["Haklı PD/DD"]["value_per_share"])
        self.assertIsNone(models["Residual Income"]["value_per_share"])
        self.assertEqual(models["Monetizasyon DCF"]["status"], "VERİ EKSİK")
        self.assertEqual(models["FCFF DCF"]["status"], "UYGUN DEĞİL")

    def test_gyo_equity_support_becomes_conditional_only_with_ke_and_growth(self) -> None:
        report = build_valuation_policy(
            "GYO",
            "Real Estate",
            {
                "roe": 28.0,
                "equity": 5_000_000.0,
                "cost_of_equity": 0.18,
                "long_term_growth": 0.03,
                "cfo_net_income": 1.0,
                "fcf_margin": 4.0,
            },
            PEER,
            25.0,
        )
        models = self._by_model(report)
        self.assertEqual(models["Haklı PD/DD"]["status"], "KOŞULLU")
        self.assertEqual(models["Residual Income"]["status"], "KOŞULLU")
        self.assertIsNone(models["Haklı PD/DD"]["value_per_share"])

    def test_bank_rejects_firm_value_models_and_keeps_pe_as_support(self) -> None:
        report = build_valuation_policy(
            "BANK",
            "Banks",
            {"roe": 25.0, "pb": 1.5, "pe": 6.0},
            PEER,
            50.0,
        )
        models = self._by_model(report)
        self.assertIn("Residual Income", report["primary_model"])
        self.assertEqual(models["Residual Income"]["status"], "KOŞULLU")
        self.assertEqual(models["F/K"]["role"], "destek")
        self.assertEqual(models["F/K"]["status"], "KOŞULLU")
        self.assertEqual(models["FCFF / FD-FAVÖK"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["EPV"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["NAD / NAV"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["Altman Z"]["status"], "UYGUN DEĞİL")

    def test_generic_positive_cash_conversion_allows_conditional_dcf(self) -> None:
        report = build_valuation_policy(
            "GENERIC",
            "Industrials",
            {"cfo_net_income": 1.15, "fcf_margin": 12.0, "operating_growth": 8.0},
            PEER,
            100.0,
        )
        models = self._by_model(report)
        self.assertEqual(report["primary_model"], "FCFF DCF")
        self.assertEqual(models["FCFF DCF"]["status"], "KOŞULLU")
        self.assertIsNone(models["FCFF DCF"]["value_per_share"])
        self.assertEqual(report["computed_values"], {})

    def test_holding_requires_sotp_and_rejects_consolidated_pe_fcff(self) -> None:
        report = build_valuation_policy(
            "GENERIC",
            "Investment Holding Companies",
            {"cfo_net_income": 1.0, "fcf_margin": 5.0, "operating_growth": 5.0},
            PEER,
            10.0,
        )
        models = self._by_model(report)
        self.assertEqual(report["primary_model"], "NAD / SOTP")
        self.assertEqual(models["NAD / SOTP"]["status"], "VERİ EKSİK")
        self.assertEqual(models["Holding İskontosu"]["status"], "VERİ EKSİK")
        self.assertEqual(models["FCFF DCF"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["F/K"]["status"], "UYGUN DEĞİL")

    def test_cyclical_sector_uses_mid_cycle_earnings_not_current_pe(self) -> None:
        report = build_valuation_policy(
            "GENERIC",
            "Airlines",
            {
                "ebitda_history": [8_000.0, 3_000.0, 6_000.0, 11_000.0, 5_000.0],
                "cfo_net_income": 1.1,
                "fcf_margin": 9.0,
            },
            PEER,
            250.0,
        )
        models = self._by_model(report)
        self.assertEqual(report["profile"], "CYCLICAL")
        self.assertEqual(report["primary_model"], "Normalize FAVÖK DCF")
        self.assertEqual(models["Normalize FAVÖK DCF"]["status"], "KOŞULLU")
        self.assertEqual(models["Çevrim Ortası FD/FAVÖK"]["status"], "KOŞULLU")
        self.assertEqual(models["EPV / Kazanç Gücü"]["status"], "KOŞULLU")
        self.assertEqual(models["FCFF DCF"]["status"], "KOŞULLU")
        self.assertEqual(models["Cari F/K"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["NAD / NAV"]["status"], "UYGUN DEĞİL")
        self.assertEqual(models["Temettü İskonto"]["status"], "UYGUN DEĞİL")
        self.assertEqual(report["computed_values"], {})


if __name__ == "__main__":
    unittest.main()
