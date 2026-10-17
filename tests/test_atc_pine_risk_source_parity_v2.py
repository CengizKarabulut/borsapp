"""Static regression gates for the COMPLETE last-uploaded Pine source.

These gates prevent A-I per-code risk plans being silently substituted by
the generic 7-bar plan. Static inspection is NOT TradingView compilation.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from market_intelligence.scanning.trade_plan import PINE_A_I


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "docs/reference/ATC_630_63_GRUP_TARAMA_StopTP_v2_20261017.pine"
)


class PineRiskWiringTests(unittest.TestCase):
    def test_all_nine_source_parameter_tuples_match_python(self):
        pine = SOURCE.read_text(encoding="utf-8")
        for letter, (scanner, spec) in zip("abcdefghi", PINE_A_I.items(), strict=True):
            pattern = rf"\\[{letter}Stop, {letter}Tp1, {letter}Tp2, {letter}Tp3\\] = f_plan\\(swing(\\d+), ema(\\d+), ([^)]+)\\)"
            match = re.search(pattern, pine)
            self.assertIsNotNone(match, letter)
            parsed = (int(match[1]), int(match[2]))
            parsed += tuple(float(x.strip()) for x in match[3].split(","))
            self.assertEqual(parsed, spec, scanner)

    def test_live_pine_packet_consumes_per_code_risk_instead_of_legacy_generic(self):
        pine = SOURCE.read_text(encoding="utf-8")
        live = pine[pine.index("f_atc_state() =>"):pine.index("type AtcPacket")]
        self.assertIn("candidateStop := switch id", live)
        self.assertIn("candidateTp1 := switch id", live)
        self.assertNotIn("candidatePlans = id <= 9 ? nativePlans", live)
        self.assertNotIn("array.get(nativePlans", live)
        self.assertIn("candidateStop := array.get(genericPlans", live)
        for number, letter in enumerate("abcdefghi", 1):
            self.assertIn(f"{number} => {letter}Stop", live)
            self.assertIn(f"{number} => {letter}Tp1", live)

    def test_pine_and_python_share_infeasible_minimum_atr_rule(self):
        pine = SOURCE.read_text(encoding="utf-8")
        body = pine[pine.index("f_plan(float swingLow"):pine.index("swing4 = ta.lowest")]
        self.assertIn("if entry - minRisk > 0.0", body)
        self.assertIn("else if raw > 0.0 and raw < entry", body)
        self.assertIn("risk := entry - raw", body)
        self.assertIn("raw := entry - risk", body)
        self.assertIn("// If no positive structural stop exists", body)

    def test_generic_short_structural_risk_is_unchanged(self):
        pine = SOURCE.read_text(encoding="utf-8")
        self.assertIn(
            "float shortRisk = math.max((swing7High + 0.2 * planAtr) - price, 0.75 * planAtr)",
            pine,
        )
        self.assertIn("array.set(plans, 7, price - 3.0 * shortRisk)", pine)


if __name__ == "__main__":
    unittest.main()
