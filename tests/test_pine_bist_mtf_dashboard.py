"""Protect the six source contexts and the reference-plan display boundary."""
from __future__ import annotations

import ast
import itertools
import re
import unittest
from pathlib import Path

from tests.test_pine_bist_notification_policy import functions

PINE = Path(__file__).resolve().parents[1] / "pine"


class PineBistMtfDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (PINE / "ATC_BIST_18_COKLU_ZAMAN.pine").read_text(encoding="utf-8")
        cls.functions = functions(cls.source)

    def test_all_thirty_numeric_functions_are_unchanged(self):
        original = functions((PINE / "ATC_BIST_18_DURUM.pine").read_text(encoding="utf-8"))
        core = {name: body for name, body in original.items() if not name.startswith("f_chart_")}
        self.assertEqual(len(core), 30)
        for name, body in core.items():
            with self.subTest(function=name):
                self.assertEqual(body, self.functions[name])

    def test_six_symbol_contexts_have_correct_last_intrabar_and_open_htf_policy(self):
        requests = re.findall(r'^AtcMtfFrame (frame\w+) = request\.security\(([^\n]+)\)$',
                              self.source, re.MULTILINE)
        self.assertEqual(len(requests), 6)
        for (name, args), tf in zip(requests, ("5", "15", "60", "240", "D", "W"), strict=True):
            with self.subTest(context=name):
                self.assertTrue(args.startswith(f'syminfo.tickerid, "{tf}", f_mtf_snapshot(),'))
                self.assertIn("gaps=barmerge.gaps_off", args)
                self.assertIn(f'lookahead=timeframe.in_seconds("{tf}") > timeframe.in_seconds() '
                              '? barmerge.lookahead_on : barmerge.lookahead_off', args)
                self.assertIn("calc_bars_count=atcBars + 30", args)
        code = "\n".join(line for line in self.source.splitlines()
                         if not line.lstrip().startswith("//"))
        self.assertIsNone(re.search(r"\b(?:alert|alertcondition|plot|plotshape)\s*\(|\bstrategy\.", code))
        self.assertIn('atcBars = input.int(600,', code)
        self.assertIn('atcR18 = input.bool(true,', code)

    def test_source_payload_is_scalar_and_plan_uses_its_own_price(self):
        payload = self.source.split("type AtcMtfFrame\n", 1)[1].split("\nf_mtf_bit", 1)[0]
        self.assertNotIn("array<", payload)
        self.assertNotIn("AtcMtfFrame", payload)
        snapshot = self.functions["f_mtf_snapshot"]
        self.assertIn("if last_bar_index - bar_index <= 2", snapshot)
        self.assertIn("time, time_close, close, volume, r18Unavailable", snapshot)
        self.assertIn("f_r18_native_snapshot(atcBars)", snapshot)
        plan = self.functions["f_mtf_plan"]
        self.assertIn("float price = frame.price", plan)
        self.assertIsNone(re.search(r"\bclose\b", plan))
        self.assertIn('f_mtf_number(frame.price), rowBg', self.source)
        self.assertIn('frameIndex != 4', self.source)  # Rule17: D1 only.
        self.assertIn('"SKOR SINIRI BELİRSİZ"', self.source)
        self.assertIn('"AKTİF NİTELİKLİ MA YOK"', self.source)

    def test_actual_tick_guard_rejects_zero_duplicate_and_reversed_prices(self):
        expression = re.search(r"^    bool displayedValid = (.+)$",
                               self.functions["f_mtf_plan"], re.MULTILINE).group(1)
        before, branches = expression.split(" and (up ? ", 1)
        long_expression, short_expression = branches.removesuffix(")").split(" : ", 1)
        allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Compare, ast.Gt, ast.Lt,
                   ast.Name, ast.Load, ast.Constant)
        predicates = []
        for branch in (long_expression, short_expression):
            tree = ast.parse(before + " and " + branch, mode="eval")
            self.assertTrue(all(isinstance(node, allowed) for node in ast.walk(tree)))
            predicates.append(compile(tree, "tick-guard", "eval"))
        names = ("displayedStop", "displayedPrice", "displayedTp1", "displayedTp2", "displayedTp3")
        for values in itertools.product((0, 1, 2, 3, 4, 5), repeat=5):
            env = dict(zip(names, values, strict=True))
            long_expected = 0 < values[0] < values[1] < values[2] < values[3] < values[4]
            short_expected = 0 < values[4] < values[3] < values[2] < values[1] < values[0]
            self.assertEqual(eval(predicates[0], {"__builtins__": {}}, env), long_expected)
            self.assertEqual(eval(predicates[1], {"__builtins__": {}}, env), short_expected)
        for name in ("price", "s", "t1", "t2", "t3"):
            self.assertIn(f"math.round_to_mintick({name})", self.functions["f_mtf_plan"])
        self.assertIn("valid := valid and displayedValid", self.functions["f_mtf_plan"])

    def test_all_matching_rows_remain_reachable_and_identify_their_timeframe(self):
        # 18 rules x six frames x three directions is the conservative upper bound.
        page_input = re.search(r'matchPageInput = input.int\(1, [^\n]+maxval=(\d+)', self.source)
        self.assertGreaterEqual(int(page_input[1]), 18 * 6 * 3)
        self.assertIn('array.from("ZAMAN", "TARAMA", "YÖN",', self.source)
        self.assertIn("int frameIndex = array.get(matchFrames, rowIndex)", self.source)
        self.assertIn("AtcMtfFrame frame = array.get(frames, frameIndex)", self.source)
        self.assertIn("int page = math.min(matchPageInput, pages)", self.source)


if __name__ == "__main__":
    unittest.main()
