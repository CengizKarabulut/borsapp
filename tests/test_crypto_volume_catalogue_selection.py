"""Guard the frozen coin selection's scope, ranking and actual identity joins."""
from __future__ import annotations

import copy
import importlib.util
import json
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "select_crypto_volume_catalogue", ROOT / "scripts" / "select_crypto_volume_catalogue.py")
selection = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(selection)


def pair(base, *, volume="100", price="1"):
    return {"Symbol": base + "USDT", "Description": base + " / TetherUS",
            "Exchange": "Binance", "Price - Currency": "USDT",
            "Price": price, "Volume in USD, 24 hours": volume}


def category(base, *, name=None, tags="DeFi"):
    return {"Instrument": base, "Description": name or base, "Category": tags}


class CryptoVolumeCatalogueSelectionTests(unittest.TestCase):
    def test_explicit_category_name_fiat_and_unknown_exclusions_do_not_guess(self):
        rows = [pair(base) for base in ("BTC", "USUAL", "QQQB", "RIF", "EUR", "UNKNOWN", "EMPTY")]
        rows[4]["Description"] = "Euro / TetherUS"
        tags = [category("BTC"), category("USUAL", tags="Stablecoins, DeFi"),
                category("QQQB", name="Invesco QQQ Tokenized bStocks"),
                category("RIF", name="Rootstock Infrastructure Framework"),
                category("EMPTY", tags="")]
        kept, excluded, below = selection.select_records(rows, tags)
        self.assertEqual([row["base"] for row in kept], ["BTC", "RIF"])
        self.assertFalse(below)
        rejected = {row["base"]: row["reasons"] for row in excluded}
        self.assertIn("explicit_stablecoins_category_tag", rejected["USUAL"])
        self.assertIn("explicit_tokenized_stock_or_etf_name", rejected["QQQB"])
        self.assertIn("explicit_euro_fiat_name", rejected["EUR"])
        self.assertIn("missing_base_category_join", rejected["UNKNOWN"])
        self.assertIn("unclassified_category_candidate", rejected["EMPTY"])

    def test_ambiguous_category_join_requires_every_candidate_to_be_allowed(self):
        rows = [pair("DOGE"), pair("PUMP"), pair("MIXED")]
        tags = [category("DOGE", name="Dogecoin"), category("DOGE", name="Another dog"),
                category("PUMP"), category("PUMP", tags=""),
                category("MIXED"), category("MIXED", tags="Stablecoins")]
        kept, excluded, _ = selection.select_records(rows, tags)
        self.assertEqual([row["base"] for row in kept], ["DOGE"])
        self.assertEqual(kept[0]["category_status"], "ambiguous_ticker")
        self.assertEqual(len(kept[0]["category_candidates"]), 2)
        self.assertEqual({row["base"] for row in excluded}, {"PUMP", "MIXED"})

    def test_ranking_is_exact_finite_positive_bounded_and_ties_are_stable(self):
        rows = [pair("BBB", volume="100.000000000000000001"), pair("AAA", volume="100"),
                pair("TIE", volume="100"), pair("NAN", volume="NaN"),
                pair("ZERO", volume="0"), pair("NEG", price="-1"),
                pair("INF", price="Infinity")]
        kept, excluded, below = selection.select_records(
            rows, [category(row["Symbol"][:-4]) for row in rows], maximum=2)
        self.assertEqual([row["base"] for row in kept], ["BBB", "AAA"])
        self.assertEqual([row["base"] for row in below], ["TIE"])
        self.assertEqual(len(excluded), 4)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            selection.select_records([rows[0], rows[0]], [category("BBB")])

    def test_qualified_id_url_and_display_name_all_must_match_actual_dom(self):
        kept, _, _ = selection.select_records([pair("BTC")], [category("BTC")])
        actual = {"ticker": "BTCUSDT", "symbol": "BINANCE:BTCUSDT",
                  "name": "BTC / TetherUS", "url": "/symbols/BTCUSDT/?exchange=BINANCE"}
        self.assertEqual(selection.qualify_records(kept, [actual])[0]["symbol"], "BINANCE:BTCUSDT")
        with self.assertRaisesRegex(ValueError, "no actual"):
            selection.qualify_records(kept, [])
        for field, value in (("symbol", "BINANCE:BTCUSDT.P"),
                             ("url", "/symbols/BTCUSDT/?exchange=OTHER"),
                             ("name", "Different asset")):
            invalid = copy.deepcopy(actual)
            invalid[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "disagrees"):
                selection.qualify_records(kept, [invalid])

    def test_shipped_subset_is_ranked_classified_qualified_and_has_one_current_part(self):
        folder = ROOT / "pine" / "catalogues"
        catalogue = json.loads((folder / "crypto-coins.json").read_text(encoding="utf-8"))
        proof = json.loads((folder / "crypto-coins.provenance.json").read_text(encoding="utf-8"))
        records = proof["records"]
        self.assertNotIn(b"\r", (folder / "crypto-coins.json").read_bytes())
        self.assertEqual(proof["catalogue_sha256"], selection.sha256(folder / "crypto-coins.json"))
        self.assertEqual(len(records), 378)
        self.assertEqual(len({row["base"] for row in records}), 378)
        self.assertEqual([row["symbol"] for row in records],
                         [row["symbol"] for row in catalogue["symbols"]])
        self.assertEqual(records, sorted(records,
                         key=lambda row: (-Decimal(row["volume_usd_24h"]), row["source_pair"])))
        self.assertTrue(all(row["symbol"].startswith("BINANCE:") for row in records))
        self.assertFalse(proof["selection"]["social_mentions_measured"])
        self.assertFalse(proof["selection"]["automatic_membership_refresh"])
        self.assertEqual(len(proof["selection"]["retained_ambiguous_symbols"]), 6)
        self.assertEqual(proof["source"]["row_count"],
                         len(records) + len(proof["exclusions"]) + len(proof["below_cutoff"]))
        self.assertEqual(len(proof["exclusions"]), 138)
        self.assertEqual(sum(item["row_count"] for item in proof["source"]["dom_captures"]), 502)
        self.assertEqual(len({row["source_pair"] for row in records + proof["exclusions"]}), 516)
        observed = [{"ticker": row["source_pair"], "symbol": row["symbol"],
                     "name": row["name"], "url": row["url"]} for row in records]
        self.assertEqual(selection.qualify_records(records, observed), records)
        for row in records:
            self.assertTrue(selection.positive(row["price"]))
            self.assertTrue(selection.positive(row["volume_usd_24h"]))
            self.assertTrue(row["category_candidates"])
            self.assertTrue(all(item["categories"] and "Stablecoins" not in item["categories"]
                                for item in row["category_candidates"]))
        generated = ROOT / "pine" / "generated" / "crypto-coins"
        self.assertEqual([path.name for path in generated.glob("*.pine")],
                         ["ATC_CRYPTO_COINS_GRUP_18_01.pine"])
        manifest = json.loads((generated / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((manifest["symbol_count"], manifest["group_count"]), (378, 38))


if __name__ == "__main__":
    unittest.main()
