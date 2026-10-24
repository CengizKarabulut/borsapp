"""Verify catalogue coverage, request budgets and requested-symbol plan isolation."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import unittest
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from tests.test_pine_bist_notification_policy import functions

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "build_global_market_groups", ROOT / "scripts" / "build_global_market_groups.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def fixture(count=23, *, coverage="complete"):
    """Synthetic catalogue solely for deterministic unit tests; never deployed."""
    return {
        "schema_version": 1, "universe_id": "synthetic-test", "title": "Synthetic fixture",
        "catalogue": {
            "source": "tradingview-screener", "url": "https://www.tradingview.com/screener/",
            "captured_at": "2026-10-23T22:00:00+03:00", "scope": "Synthetic unit-test records",
            "coverage": coverage, "row_count": count,
        },
        "symbols": [{"symbol": f"TEST:ASSET{index:04d}", "name": f"Synthetic {index}"}
                    for index in range(count)],
    }


class PineGlobalMarketGroupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = builder.GLOBAL_SOURCE.read_text(encoding="utf-8")
        cls.generated = builder.build_artifacts(fixture(), cls.source)
        cls.manifest = json.loads(cls.generated["manifest.json"])
        cls.pine = cls.generated[cls.manifest["parts"][0]["file"]].decode("utf-8")

    def test_catalogue_has_inspectable_source_scope_timestamp_and_coverage(self):
        for field in ("source", "url", "captured_at", "scope", "coverage", "row_count"):
            invalid = fixture()
            del invalid["catalogue"][field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                builder.validate_catalogue(invalid)
        for url in ("https://tradingview.com.attacker.invalid/screener/",
                    "http://www.tradingview.com/screener/",
                    "https://user:password@www.tradingview.com/screener/"):
            invalid = fixture()
            invalid["catalogue"]["url"] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                builder.validate_catalogue(invalid)
        invalid = fixture()
        invalid["catalogue"]["captured_at"] = "2026-10-23T22:00:00"
        with self.assertRaisesRegex(ValueError, "timezone"):
            builder.validate_catalogue(invalid)

    def test_duplicate_or_unqualified_symbols_cannot_silently_reduce_coverage(self):
        invalid = fixture()
        invalid["symbols"][1] = copy.deepcopy(invalid["symbols"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            builder.validate_catalogue(invalid)
        for symbol in ("AAPL", "nasdaq:AAPL", "BINANCE:BTCUSDT\n", 'TEST:BAD")\nalert("oops',
                       "", "TEST:BAD\\NAME"):
            invalid = fixture()
            invalid["symbols"][0]["symbol"] = symbol
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                builder.validate_catalogue(invalid)
        invalid = fixture()
        invalid["catalogue"]["row_count"] += 1
        with self.assertRaisesRegex(ValueError, "row_count"):
            builder.validate_catalogue(invalid)

    def test_partial_catalogue_is_always_labelled_partial(self):
        artifacts = builder.build_artifacts(fixture(coverage="partial"), self.source)
        manifest = json.loads(artifacts["manifest.json"])
        content = artifacts[manifest["parts"][0]["file"]].decode()
        self.assertEqual(manifest["catalogue"]["coverage"], "partial")
        self.assertIn('string coverage = "KISMİ KATALOG"', content)
        self.assertNotIn('string coverage = "TAM KATALOG"', content)

    def test_source_labels_cannot_disguise_symbol_pages_as_a_screener_export(self):
        for source in ("tradingview-screener", "tradingview-symbol-pages", "tradingview-components"):
            catalogue = fixture()
            catalogue["catalogue"]["source"] = source
            actual = builder.validate_catalogue(catalogue)
            self.assertEqual(actual["catalogue"]["source"], source)
        for source in ("guessed-symbols", "other-site", "tradingview-unknown", ""):
            catalogue = fixture()
            catalogue["catalogue"]["source"] = source
            with self.subTest(source=source), self.assertRaises(ValueError):
                builder.validate_catalogue(catalogue)

    def test_partition_covers_every_record_once_with_no_padding_requests(self):
        for count in (1, 9, 10, 11, 631, 1000, 1001, 2037):
            with self.subTest(count=count):
                catalogue = fixture(count)
                artifacts = builder.build_artifacts(catalogue, self.source)
                manifest = json.loads(artifacts["manifest.json"])
                actual = [symbol for part in manifest["parts"] for symbol in part["symbols"]]
                self.assertEqual(actual, [record["symbol"] for record in catalogue["symbols"]])
                self.assertEqual(len(set(actual)), count)
                self.assertEqual(manifest["group_count"], (count + 9) // 10)
                self.assertEqual(manifest["parts"][0]["global_group_first"], 1)
                self.assertEqual(manifest["parts"][-1]["global_group_last"], (count + 9) // 10)
                for part in manifest["parts"]:
                    self.assertLessEqual(part["symbol_count"], 1000)
                    self.assertEqual(part["sha256"], builder.sha256(artifacts[part["file"]]))
        self.assertIn("int groupSize = math.min(10, array.size(groupUniverse) - groupStart)", self.pine)
        self.assertIn("for memberIndex = 0 to groupSize - 1", self.pine)
        self.assertNotIn("for memberIndex = 0 to 9", self.pine)

    def test_groups_are_not_capped_at_bist_64(self):
        artifacts = builder.build_artifacts(fixture(1000), self.source)
        manifest = json.loads(artifacts["manifest.json"])
        content = artifacts[manifest["parts"][0]["file"]].decode()
        self.assertEqual(manifest["group_count"], 100)
        self.assertIn('"Bu dosyadaki grup", minval=1, maxval=100', content)
        self.assertNotIn("maxval=64", content)

    def test_large_catalogue_constructors_bound_arguments_and_preserve_each_value(self):
        def constructor_values(expression):
            """Parse emitted string arguments without splitting commas in names."""
            decoder = json.JSONDecoder()
            chunks = []
            for match in re.finditer(r"\barray\.from\(", expression):
                cursor = match.end()
                values = []
                while True:
                    while expression[cursor].isspace():
                        cursor += 1
                    value, cursor = decoder.raw_decode(expression, cursor)
                    self.assertIsInstance(value, str)
                    values.append(value)
                    while expression[cursor].isspace():
                        cursor += 1
                    if expression[cursor] == ")":
                        break
                    self.assertEqual(expression[cursor], ",")
                    cursor += 1
                chunks.append(values)
            return chunks

        for count in (499, 500, 501, 999, 1000):
            with self.subTest(count=count):
                catalogue = fixture(count)
                catalogue["symbols"][0]["name"] = 'A (name), with "quotes"'
                artifacts = builder.build_artifacts(catalogue, self.source)
                manifest = json.loads(artifacts["manifest.json"])
                self.assertEqual(len(manifest["parts"]), 1)
                self.assertEqual(manifest["parts"][0]["symbol_count"], count)
                content = artifacts[manifest["parts"][0]["file"]].decode()
                for variable, key, next_declaration in (
                        ("groupUniverse", "symbol", "groupNames"),
                        ("groupNames", "name", "frameLabels")):
                    expression = content.split(f"var array<string> {variable} = ", 1)[1]
                    expression = expression.split(f"\nvar array<string> {next_declaration}", 1)[0]
                    chunks = constructor_values(expression)
                    self.assertEqual([len(chunk) for chunk in chunks],
                                     [count] if count <= 500 else [500, count - 500])
                    self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))
                    self.assertEqual([value for chunk in chunks for value in chunk],
                                     [record[key] for record in catalogue["symbols"]])
                    self.assertEqual(expression.count("array.concat("), int(count > 500))

    def test_part_size_cannot_break_global_group_boundaries_or_resource_bound(self):
        for size in (0, 9, 11, 1001, 10000, True):
            with self.subTest(size=size), self.assertRaises(ValueError):
                builder.build_artifacts(fixture(), self.source, max_symbols_per_part=size)

    def test_names_are_literal_data_not_pine_or_template_code(self):
        catalogue = fixture(1)
        catalogue["symbols"][0]["name"] = 'A "quoted" name · @@CORE@@'
        artifacts = builder.build_artifacts(catalogue, self.source)
        manifest = json.loads(artifacts["manifest.json"])
        content = artifacts[manifest["parts"][0]["file"]].decode()
        self.assertIn('"A \\"quoted\\" name · @@CORE@@"', content)
        self.assertEqual(content.count("f_global_bist_reference() =>"), 1)

    def test_generated_core_preserves_every_existing_function_exactly(self):
        original = functions(self.source)
        actual = functions(self.pine)
        start = self.source.index("f_global_bist_reference() =>")
        end = self.source.index("// Request calls execute on all chart bars", start)
        core_functions = functions(self.source[start:end])
        self.assertGreaterEqual(len(core_functions), 38)
        for name in core_functions:
            with self.subTest(function=name):
                normalized = actual[name]
                if name == "f_mtf_snapshot":
                    normalized = normalized.replace(
                        ", syminfo.mintick, syminfo.timezone, syminfo.currency, syminfo.volumetype)", ")")
                self.assertEqual(original[name], normalized)

    def test_udt_scalar_fields_carry_requested_context_metadata(self):
        udt = self.pine.split("type AtcMtfFrame\n", 1)[1].split("\nf_mtf_bit", 1)[0]
        for field in ("float sourceTick", "string sourceZone", "string sourceCurrency",
                      "string sourceVolumeKind", "int sourceBars"):
            self.assertIn(field, udt)
        self.assertNotIn("array<", udt)
        constructor = re.search(r"result := AtcMtfFrame\.new\(([^\n]+)\)", self.pine)[1]
        self.assertTrue(constructor.endswith(
            "syminfo.mintick, syminfo.timezone, syminfo.currency, syminfo.volumetype"))

    def test_request_budget_is_four_frames_times_actual_maximum_ten_symbols(self):
        requests = re.findall(r"AtcMtfFrame frame\w+ = request\.security\(([^\n]+)\)", self.pine)
        self.assertEqual(len(requests), 4)
        for args, timeframe in zip(requests, ("60", "240", "D", "W"), strict=True):
            self.assertTrue(args.startswith(f'requestedSymbol, "{timeframe}", f_mtf_snapshot(),'))
            self.assertIn("ignore_invalid_symbol=true", args)
            self.assertIn("calc_bars_count=atcBars + 30", args)
            self.assertIn(f'timeframe.in_seconds("{timeframe}") > timeframe.in_seconds() '
                          '? barmerge.lookahead_on : barmerge.lookahead_off', args)
        self.assertEqual(self.manifest["maximum_unique_requests"], 40)
        # Requests must preload on historical bars, outside the last-bar table block.
        self.assertLess(self.pine.index("for memberIndex = 0 to groupSize - 1"),
                        self.pine.index("if barstate.islast\n"))

    def test_group_plan_does_not_borrow_host_tick_or_timezone(self):
        actual = functions(self.pine)
        body = actual["f_group_plan"]
        self.assertNotIn("math.round_to_mintick", body)
        self.assertNotIn("syminfo.", body)
        self.assertEqual(body.count("frame.sourceTick"), 5)
        self.assertIn("rawValid and roundedValid", body)
        display = self.pine.split("if barstate.islast\n", 1)[1]
        self.assertNotIn("format.mintick", display)
        self.assertNotIn("syminfo.timezone", display)
        self.assertIn("frame.sourceZone", display)
        self.assertIn("frame.sourceTick", display)
        self.assertIn("frame.sourceCurrency", display)
        self.assertIn('"\\nStop mesafesi: %"', display)
        self.assertIn("math.abs(s - frame.price) / frame.price * 100.0", display)

    def test_realistic_tiny_coin_tick_and_futures_tick_remain_distinct(self):
        # A host priced in 0.25 increments must not round a tiny coin to zero.
        def rounded(value, tick):
            step = Decimal(tick)
            return (Decimal(value) / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step
        self.assertEqual(rounded("0.000012345", "0.000000001"), Decimal("0.000012345"))
        self.assertEqual(rounded("13901.14", "0.25"), Decimal("13901.25"))
        self.assertEqual(rounded("0.000012345", "0.25"), Decimal("0.00"))
        rounding = functions(self.pine)["f_group_round"]
        self.assertIn("math.round(value / tick) * tick", rounding)
        self.assertIn("tick > 0.0", rounding)

    def test_missing_history_and_volume_are_not_silently_no_match(self):
        body = functions(self.pine)["f_group_state"]
        self.assertIn("frame.sourceBars < f_mtf_min_bars(id)", body)
        self.assertIn('str.tostring(f_mtf_min_bars(id)) + " MUM"', body)
        self.assertIn('"TİK HACMİ" : "HACİM YOK"', body)
        self.assertIn('id == 17 and tfIndex != 2 ? "1G ÖZEL"', body)
        self.assertIn('not present ? "VERİ YOK"', body)
        self.assertIn('"MA YOK"', body)

    def test_number_labels_use_source_tick_precision_without_binary_tails(self):
        def digits(tick):
            scaled = float(tick)
            result = 0
            while result < 16 and (scaled < 1.0 or abs(scaled - round(scaled)) > 1e-8):
                scaled *= 10.0
                result += 1
            return result

        for tick, expected in ((1, 0), (0.25, 2), (0.01, 2), (1e-9, 9), (1e-16, 16)):
            self.assertEqual(digits(tick), expected)
        for value, tick, label in ((70.35000000000001, .01, '70.35'),
                                   (17.830000000000002, .01, '17.83'),
                                   (0.000012345, 1e-9, '0.000012345'),
                                   (13901.25, .25, '13901.25')):
            self.assertEqual(f'{value:.{digits(tick)}f}', label)
        formatter = functions(self.pine)['f_group_number']
        self.assertIn('scaled < 1.0 or', functions(self.pine)['f_group_tick_digits'])
        self.assertIn('f_group_tick_digits(tick)', formatter)
        self.assertNotIn('syminfo.', formatter)
        self.assertNotIn('#.################', formatter)
        for precision in range(1, 17):
            self.assertIn('"#.' + '0' * precision + '"', formatter)

    def test_grouped_view_cannot_submit_orders_or_send_notifications(self):
        code = "\n".join(line for line in self.pine.splitlines()
                         if not line.lstrip().startswith("//"))
        self.assertIsNone(re.search(r"\b(?:alert|alertcondition|plot|plotshape)\s*\(|\bstrategy\.", code))
        self.assertTrue(self.manifest["display_only"])
        self.assertFalse(self.manifest["alerts_created"])
        self.assertFalse(self.manifest["calibrated_profiles"])
        self.assertEqual(self.manifest["runtime_validation"], "pending_tradingview_compile_and_feed_check")

    def test_build_is_deterministic_and_manifest_links_exact_catalogue_and_source(self):
        self.assertEqual(self.generated, builder.build_artifacts(fixture(), self.source))
        self.assertEqual(self.manifest["catalogue_sha256"],
                         builder.sha256(self.generated["catalogue.json"]))
        self.assertEqual(self.manifest["global_source_sha256"],
                         builder.sha256(self.source.encode("utf-8")))

    def test_checked_in_market_packages_cannot_drift_from_source_or_catalogue(self):
        for market in ('crypto-coins', 'us-index-equities', 'viop-continuous'):
            with self.subTest(market=market):
                target = ROOT / 'pine' / 'generated' / market
                raw = json.loads((target / 'catalogue.json').read_text(encoding='utf-8'))
                expected = builder.build_artifacts(raw, self.source)
                for name, content in expected.items():
                    self.assertEqual((target / name).read_bytes(), content, f'{market}/{name}')


if __name__ == "__main__":
    unittest.main()
