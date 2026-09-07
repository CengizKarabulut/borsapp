import unittest

from src.state_change import compare_states


def state(**overrides):
    payload = {
        "setup_context": {
            "setup": {"name": "Sıkışma / karar bölgesi", "bias": "iki yönlü", "tone": "neutral"},
            "duration": {"squeeze_bars": 7},
            "participation_reading": {"state": "Sıkışmayla uyumlu düşük katılım", "tone": "neutral"},
        },
        "structure": {"state": "LH / LL", "tone": "negative"},
        "regime": {"state": "Denge / sıkışma"},
        "profile": {"position": "Value Area içinde", "tone": "neutral"},
        "semantic": {
            "trend_quality": {"state": "EMA dizilimi parçalı", "tone": "warning"},
            "momentum_character": {"state": "Negatif ve genişleyen momentum", "tone": "negative"},
            "participation": {"rvol_1": 0.56},
            "level_confluence": {"clusters": [{"side": "destek", "low": 297.56, "high": 299.50}]},
        },
        "relative_strength": {"ratio_slope_5_pct": -3.16},
        "clarity_state": "Düşük",
    }
    payload.update(overrides)
    return payload


class StateChangeTests(unittest.TestCase):
    def test_missing_previous_state_is_reported_not_crashed(self) -> None:
        result = compare_states(None, state())
        self.assertFalse(result["available"])
        self.assertIn("karşılaştırma yapılamıyor", result["bullets"][0].casefold())

    def test_identical_states_report_no_change(self) -> None:
        result = compare_states(state(), state())
        self.assertTrue(result["available"])
        self.assertEqual(result["items"], [])
        self.assertIn("değişiklik yok", result["bullets"][0])

    def test_setup_change_is_detected(self) -> None:
        previous = state()
        current = state()
        current["setup_context"]["setup"]["name"] = "Destekte reddedilme / başarısız aşağı kırılım"
        result = compare_states(previous, current)
        self.assertIn("Kurulum değişti", result["bullets"][0])
        self.assertIn("Sıkışma / karar bölgesi", result["bullets"][0])

    def test_value_area_transition_is_detected(self) -> None:
        previous = state()
        current = state()
        current["profile"]["position"] = "Value Area altında"
        texts = " ".join(compare_states(previous, current)["bullets"])
        self.assertIn("value area altında", texts.casefold())

    def test_squeeze_exit_is_reported_with_duration(self) -> None:
        previous = state()
        current = state()
        current["setup_context"]["duration"]["squeeze_bars"] = 0
        texts = " ".join(compare_states(previous, current)["bullets"])
        self.assertIn("7 bardır süren dar bant bölgesinden çıkıldı", texts)

    def test_relative_strength_flip_is_detected(self) -> None:
        previous = state()
        current = state()
        current["relative_strength"]["ratio_slope_5_pct"] = 1.20
        texts = " ".join(compare_states(previous, current)["bullets"])
        self.assertIn("güçlenmeye döndü", texts)

    def test_small_rvol_move_is_ignored_but_large_one_is_not(self) -> None:
        previous = state()
        small = state()
        small["semantic"]["participation"]["rvol_1"] = 0.60
        self.assertEqual(compare_states(previous, small)["items"], [])
        large = state()
        large["semantic"]["participation"]["rvol_1"] = 1.40
        texts = " ".join(compare_states(previous, large)["bullets"])
        self.assertIn("RVOL belirgin biçimde arttı", texts)

    def test_zero_width_cluster_is_printed_as_single_level(self) -> None:
        previous = state()
        current = state()
        current["semantic"]["level_confluence"]["clusters"] = [{"side": "direnç", "low": 146.82, "high": 146.82}]
        texts = " ".join(compare_states(previous, current)["bullets"])
        self.assertIn("(146.82)", texts)
        self.assertNotIn("146.82–146.82", texts)

    def test_output_is_capped(self) -> None:
        previous = state()
        current = state()
        current["setup_context"]["setup"]["name"] = "Trend devamı"
        current["setup_context"]["setup"]["bias"] = "aşağı"
        current["structure"]["state"] = "HH / HL"
        current["regime"]["state"] = "Trend / yönlü piyasa"
        current["profile"]["position"] = "Value Area üzerinde"
        current["semantic"]["trend_quality"]["state"] = "Tam bullish EMA dizilimi"
        current["semantic"]["momentum_character"]["state"] = "Pozitif ve genişleyen momentum"
        current["clarity_state"] = "Yüksek"
        self.assertLessEqual(len(compare_states(previous, current)["items"]), 6)


if __name__ == "__main__":
    unittest.main()
