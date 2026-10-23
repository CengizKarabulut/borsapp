"""Check portable market boundaries without changing the BIST reference core."""
from __future__ import annotations

import ast
import itertools
import re
import unittest
from pathlib import Path

from tests.test_pine_bist_notification_policy import functions

PINE = Path(__file__).resolve().parents[1] / "pine"


def predicate(expression, **values):
    """Evaluate the actual Pine boolean subset, rejecting executable constructs."""
    tree = ast.parse(expression, mode="eval")
    allowed = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not,
               ast.Compare, ast.Gt, ast.GtE, ast.Eq, ast.Name, ast.Load, ast.Constant)
    if not all(isinstance(node, allowed) for node in ast.walk(tree)):
        raise AssertionError("Unexpected expression outside the tested boolean subset")
    return eval(compile(tree, "pine-policy", "eval"), {"__builtins__": {}}, values)


class PineGlobalMtfDashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (PINE / "ATC_GLOBAL_18_COKLU_ZAMAN.pine").read_text(encoding="utf-8")
        cls.functions = functions(cls.source)
        cls.original = functions((PINE / "ATC_BIST_18_COKLU_ZAMAN.pine").read_text(encoding="utf-8"))

    def test_bist_numerics_have_only_the_documented_market_policy_changes(self):
        changed = {"f_r1016_snapshot", "f_r17_frame", "f_r17_bear_frame"}
        originals = {name: body for name, body in self.original.items()
                     if not name.startswith("f_mtf_")}
        self.assertEqual(len(originals), 30)
        for name, original in originals.items():
            with self.subTest(function=name):
                actual = self.functions[name]
                if name == "f_r1016_snapshot":
                    actual = actual.replace(
                        "f_global_activity(array.get(closes, i), array.get(volumes, i))",
                        "array.get(closes, i) * array.get(volumes, i)")
                    actual = actual.replace("f_global_liquid(volumeKnown, price, turnover)",
                                            "volumeKnown and price >= 1.0 and turnover >= 20000000.0")
                elif name in changed:
                    actual = actual.replace("f_global_activity(close[offset], volume[offset])",
                                            "close[offset] * volume[offset]")
                    actual = actual.replace("f_global_activity(c, v)", "c * v")
                self.assertEqual(original, actual)

    def test_actual_gate_preserves_bist_and_accepts_subunit_crypto_prices(self):
        expression = self.functions["f_global_liquid"].splitlines()[-1].strip()
        for bist, volume, price, turnover in itertools.product(
                (False, True), (False, True), (-1, 0, 0.00001, 0.99, 1, 100),
                (0, 19_999_999, 20_000_000, 100_000_000)):
            actual = predicate(expression, bistReference=bist, volumeKnown=volume,
                               price=price, turnover=turnover)
            expected = volume and (price >= 1 and turnover >= 20_000_000 if bist else price > 0)
            self.assertEqual(actual, expected, (bist, volume, price, turnover))

    def test_exchange_does_not_misclassify_viop_as_cash_bist(self):
        body = self.functions["f_global_bist_reference"]
        expressions = {}
        for name in ("bistExchange", "cashType"):
            expression = re.search(rf"bool {name} = (.+)", body)[1]
            expressions[name] = expression.replace("syminfo.prefix", "prefix").replace(
                "syminfo.type", "kind")
        result = body.splitlines()[-1].strip().replace("syminfo.currency", "currency")
        for prefix, kind, currency, expected in (
                ("BIST", "stock", "TRY", True), ("BIST_DLY", "fund", "TRY", True),
                ("BIST", "futures", "TRY", False), ("BIST", "index", "TRY", False),
                ("NASDAQ", "stock", "USD", False), ("BINANCE", "crypto", "USDT", False),
                ("BIST", "stock", "USD", False), ("COMEX", "futures", "USD", False)):
            values = {"prefix": prefix, "kind": kind, "currency": currency}
            values["bistExchange"] = predicate(expressions["bistExchange"], **values)
            values["cashType"] = predicate(expressions["cashType"], **values)
            self.assertEqual(predicate(result, **values), expected, values)

    def test_quote_volume_is_not_multiplied_twice_and_no_pnl_conversion_occurs(self):
        activity = self.functions["f_global_activity"]
        self.assertIn('not f_global_bist_reference() and syminfo.volumetype == "quote" '
                      '? sourceVolume : price * sourceVolume', activity)
        # The three consumers use the same policy for numerator and baseline.
        self.assertEqual(self.source.count("f_global_activity("), 6)
        plan = self.functions["f_mtf_plan"]
        self.assertEqual(plan, self.original["f_mtf_plan"])
        self.assertNotIn("pointvalue", plan)
        self.assertIn('"Vadeli: kontrat/seans/roll kontrolü', self.source)

    def test_missing_and_tick_volume_do_not_become_a_false_no_match(self):
        snapshot = self.functions["f_mtf_snapshot"]
        self.assertIn('na(volume) or volume < 0.0 ? 0 : syminfo.volumetype == "tick" ? 3', snapshot)
        self.assertNotIn('syminfo.volumetype == "n/a"', snapshot)
        self.assertNotIn("nz(volume", snapshot)
        self.assertIn("if atcComplex and volumeTrusted", snapshot)
        self.assertIn("if atcR18 and volumeTrusted", snapshot)
        self.assertIn("ruleReady and array.get(legacyFlags, i)", snapshot)
        self.assertIn("i < 2 or volumeTrusted", snapshot)
        self.assertIn('"TİK HACMİ" : "HACİM YOK"', self.source)
        self.assertIn('"KOŞUL YOK"', self.source)
        self.assertIn('"SKOR SINIRI BELİRSİZ"', self.source)

    def test_six_current_symbol_contexts_remain_display_only(self):
        requests = re.findall(r'^AtcMtfFrame (frame\w+) = request\.security\(([^\n]+)\)$',
                              self.source, re.MULTILINE)
        self.assertEqual(len(requests), 6)
        for (_, args), tf in zip(requests, ("5", "15", "60", "240", "D", "W"), strict=True):
            self.assertTrue(args.startswith(f'syminfo.tickerid, "{tf}", f_mtf_snapshot(),'))
            self.assertIn(f'timeframe.in_seconds("{tf}") > timeframe.in_seconds() '
                          '? barmerge.lookahead_on : barmerge.lookahead_off', args)
        code = "\n".join(line for line in self.source.splitlines()
                         if not line.lstrip().startswith("//"))
        self.assertIsNone(re.search(r"\b(?:alert|alertcondition|plot|plotshape)\s*\(|\bstrategy\.", code))
        payload = self.source.split("type AtcMtfFrame\n", 1)[1].split("\nf_mtf_bit", 1)[0]
        self.assertNotIn("array<", payload)
        self.assertIn("int volumeState", payload)
        self.assertIn("frameIndex != 4", code)
        self.assertIn("maxval=324", code)
        self.assertIn("syminfo.timezone", code)
        self.assertIn("syminfo.session", code)


if __name__ == "__main__":
    unittest.main()
