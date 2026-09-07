import unittest

from src.scan_card import _candidate_commentary, sort_scan_results


def item(
    ticker: str,
    bias: str,
    score: float,
    excess: float,
    *,
    rvol: float = 1.8,
) -> dict:
    return {
        "ticker": ticker,
        "close": 100.0,
        "setup": "Trend devamı" if bias != "iki yönlü" else "Sıkışma / karar bölgesi",
        "setup_bias": bias,
        "score": score,
        "excess_return_20": excess,
        "rvol": rvol,
        "matched_intervals": ["1h", "4h"],
        "active_levels": {
            "lower": 96.0,
            "reference_close": 100.0,
            "upper": 104.0,
        },
    }


class ScanCandidatePriorityTests(unittest.TestCase):
    def test_positive_candidates_come_before_conditional_and_negative(self) -> None:
        results = sort_scan_results(
            [
                item("NEG", "aşağı", 20.0, -7.0),
                item("KARAR", "iki yönlü", 30.0, 5.0),
                item("POZ", "yukarı", 5.0, 1.0),
            ]
        )
        self.assertEqual([entry["ticker"] for entry in results], ["POZ", "KARAR", "NEG"])

    def test_quality_score_orders_candidates_inside_positive_group(self) -> None:
        results = sort_scan_results(
            [
                item("LOW", "yukarı", 4.0, 5.0),
                item("HIGH", "yukarı", 8.0, 1.0),
            ]
        )
        self.assertEqual([entry["ticker"] for entry in results], ["HIGH", "LOW"])

    def test_positive_commentary_explains_strength_and_confirmation(self) -> None:
        text = _candidate_commentary(item("POZ", "yukarı", 8.0, 3.2))
        self.assertIn("Pozitif eğilim önde", text)
        self.assertIn("XU100'a göre +3.2 puan güçlü", text)
        self.assertIn("RVOL 1.8x", text)
        self.assertIn("104.00 üstü kapanış", text)
        self.assertIn("96.00 altı", text)

    def test_conditional_commentary_does_not_pretend_direction_is_known(self) -> None:
        text = _candidate_commentary(item("KARAR", "iki yönlü", 10.0, 1.0))
        self.assertIn("Yön henüz net değil", text)
        self.assertIn("tek başına kırılım yönü söylemez", text)


if __name__ == "__main__":
    unittest.main()
