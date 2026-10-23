"""Guard preserved chart formulas and LONG-only notification boundaries."""
from __future__ import annotations

import ast
import itertools
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "pine"
ALARM_FILES = ("ATC_TV200_LONG_REFERENCE.pine", "ATC_BIST631_LONG_REFERENCE.pine")
CORES = ("f_native_legacy_snapshot", "f_r1016_snapshot", "f_r17_frame",
         "f_r17_bear_frame", "f_r18_native_snapshot")


def functions(source):
    lines = source.splitlines()
    result = {}
    for offset, line in enumerate(lines):
        match = re.match(r"^(f_\w+)\(.*\)\s*=>\s*$", line)
        if match is None:
            continue
        end = offset + 1
        while end < len(lines) and (not lines[end].strip() or lines[end].startswith(" ")):
            end += 1
        result[match[1]] = "\n".join(lines[offset:end]).rstrip()
    return result


class PineBistNotificationPolicyTests(unittest.TestCase):
    def test_dashboard_reuses_same_numeric_cores_without_alerts_or_security(self):
        chart = (ROOT / "ATC_BIST_18_DURUM.pine").read_text(encoding="utf-8")
        self.assertTrue(chart.startswith("//@version=6"))
        code = "\n".join(line for line in chart.splitlines() if not line.lstrip().startswith("//"))
        self.assertIsNone(re.search(r"\b(?:alert|alertcondition)\s*\(|\b(?:request|strategy)\.", code))
        chart_functions = functions(chart)
        for name in ALARM_FILES:
            with self.subTest(source=name):
                source_functions = functions((ROOT / name).read_text(encoding="utf-8"))
                for core in CORES:
                    self.assertIn(core, chart_functions)
                    self.assertEqual(chart_functions[core], source_functions[core], core)

    def test_only_long_can_enter_queue_without_changing_long_event_conditions(self):
        names = ("up", "realtime", "initialized", "humanInitial", "active", "seen",
                 "stronger", "becameActive", "initialActive")
        for filename in ALARM_FILES:
            source = (ROOT / filename).read_text(encoding="utf-8")
            observe = functions(source)["f_human_observe"]
            expression = re.search(r"^\s+bool notify = (.+)$", observe, re.MULTILINE).group(1)
            tree = ast.parse(expression, mode="eval")
            allowed = (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.And, ast.Or, ast.Not,
                       ast.Name, ast.Load)
            self.assertTrue(all(isinstance(node, allowed) for node in ast.walk(tree)))
            self.assertEqual({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}, set(names))
            predicate = compile(tree, filename, "eval")
            for values in itertools.product((False, True), repeat=len(names)):
                env = dict(zip(names, values, strict=True))
                old_long = (env["realtime"] and (env["initialized"] or env["humanInitial"])
                    and env["active"] and (not env["seen"] or env["stronger"])
                    and (env["becameActive"] or env["stronger"] or env["initialActive"]))
                self.assertEqual(eval(predicate, {"__builtins__": {}}, env), env["up"] and old_long)
            self.assertIn("f_human_clear(firstSlot + 1)", observe)
            self.assertIn("if slot % 2 == 0 and array.get(humanPending, slot)", source)

    def test_both_symbol_universes_remain_complete_and_unique(self):
        for filename, expected in zip(ALARM_FILES, (200, 631), strict=True):
            with self.subTest(source=filename):
                source = (ROOT / filename).read_text(encoding="utf-8")
                symbols = re.search(r'atcUniverse = str.split\("([^"]+)"', source).group(1).split("|")
                self.assertEqual(len(symbols), expected)
                self.assertEqual(len(set(symbols)), expected)
                self.assertTrue(all(symbol.startswith("BIST:") for symbol in symbols))


if __name__ == "__main__":
    unittest.main()
