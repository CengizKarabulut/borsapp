from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from market_intelligence.fundamentals.archive import FinancialArchive
from market_intelligence.fundamentals.providers import FinancialProviderChain, _snapshot_from_frames
from market_intelligence.fundamentals.quotes import MarketQuote, MarketQuoteProvider, apply_quote
from tests.test_provider_fallbacks import StubFinancialProvider


class ArchiveTests(unittest.TestCase):
    def test_statement_currency_has_priority_over_quote_currency(self):
        snapshot = _snapshot_from_frames(
            provider_id="test",
            symbol="ASELS",
            as_of=datetime.now(UTC),
            balance=None,
            income=None,
            cashflow=None,
            info={"financialCurrency": "USD", "currency": "TRY"},
            fast={},
        )
        self.assertEqual(snapshot.currency, "USD")

    def test_unverified_monetary_basis_blocks_rolling_sum(self):
        args = dict(
            provider_id="test",
            symbol="ASELS",
            as_of=datetime(2026, 9, 10, tzinfo=UTC),
            balance=None,
            cashflow=None,
            info={},
            fast={},
            cumulative_flows=True,
            common_purchasing_power=False,
        )
        frame = pd.DataFrame(
            {"2026-06-30": [70], "2025-12-31": [100], "2025-06-30": [40]}, index=["Total Revenue"]
        )
        result = _snapshot_from_frames(income=frame, **args)
        self.assertIsNone(result.metrics["revenue_ttm"])
        self.assertEqual(result.metadata["period_aggregation"], "blocked_unverified_basis")
        annual = _snapshot_from_frames(income=frame.drop(columns=["2026-06-30"]), **args)
        self.assertEqual(annual.metrics["revenue_ttm"], 100)
        self.assertIsNone(annual.metrics["revenue_growth"])

    def test_backup_restores_snapshot_and_detects_corrupt_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = FinancialArchive(root / "live")
            raw = archive.root / "kap" / "123" / "raw.json"
            raw.parent.mkdir(parents=True)
            raw.write_bytes(b'{"value":42}')
            now = datetime.now(UTC)
            archive.put(
                "ASELS",
                "kap",
                "report",
                {
                    "raw_path": "kap/123/raw.json",
                    "raw_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                },
                observed_at=now,
            )
            result = archive.backup(root / "backup")
            self.assertEqual(len(result["files"]), 2)
            restored = FinancialArchive(root / "backup")
            self.assertIsNotNone(restored.latest("ASELS", "kap", "report", known_at=now))
            self.assertEqual((restored.root / "kap/123/raw.json").read_bytes(), raw.read_bytes())
            with self.assertRaises(FileExistsError):
                archive.backup(root / "backup")
            raw.write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "checksum"):
                archive.backup(root / "bad-backup")
            self.assertFalse((root / "bad-backup/backup-manifest.json").exists())

    def test_revisions_and_observation_cutoff(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = FinancialArchive(Path(folder))
            now = datetime(2026, 9, 10, tzinfo=UTC)
            archive.put("ASELS", "kap", "statement", {"profit": 10}, observed_at=now)
            archive.put(
                "ASELS", "kap", "statement", {"profit": 12}, observed_at=now + timedelta(days=1)
            )
            self.assertIsNone(
                archive.latest("ASELS", "kap", "statement", known_at=now - timedelta(seconds=1))
            )
            self.assertEqual(
                archive.latest("ASELS", "kap", "statement", known_at=now)[2]["profit"], 10
            )
            self.assertEqual(
                archive.latest("ASELS", "kap", "statement", known_at=now + timedelta(days=2))[2][
                    "profit"
                ],
                12,
            )

    def test_frames_preserve_missing_cells_and_periods(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = FinancialArchive(Path(folder))
            now = datetime(2026, 9, 10, tzinfo=UTC)
            frame = pd.DataFrame({"2026Q2": [1.0, None]}, index=["revenue", "cash"])
            archive.put_frames(
                "ASELS",
                "test",
                frames={"income": frame},
                info={},
                fast={},
                observed_at=now,
                cumulative=True,
            )
            fetched = archive.frames("ASELS", "test", known_at=now)
            pd.testing.assert_frame_equal(fetched[2]["income"], frame)


class FinancialSafetyTests(unittest.TestCase):
    def snapshot(self, balance, cashflow):
        return _snapshot_from_frames(
            provider_id="test",
            symbol="ASELS",
            as_of=datetime(2026, 9, 10, tzinfo=UTC),
            balance=balance,
            income=pd.DataFrame({"2025-12-31": [200]}, index=["revenue"]),
            cashflow=cashflow,
            info={"currency": "TRY"},
            fast={},
            cumulative_flows=True,
        )

    def test_missing_capex_and_cash_do_not_become_zero(self):
        result = self.snapshot(
            pd.DataFrame({"2025-12-31": [20, 30]}, index=["short term debt", "long term debt"]),
            pd.DataFrame({"2025-12-31": [100]}, index=["operating cash flow"]),
        )
        self.assertIsNone(result.metrics["fcf_ttm"])
        self.assertIsNone(result.metrics["net_debt"])
        self.assertEqual(result.metrics["total_debt"], 50)

    def test_explicit_zero_capex_is_valid(self):
        result = self.snapshot(
            None,
            pd.DataFrame(
                {"2025-12-31": [100, 0]}, index=["operating cash flow", "capital expenditure"]
            ),
        )
        self.assertEqual(result.metrics["fcf_ttm"], 100)

    def test_missing_debt_component_stays_unknown(self):
        result = self.snapshot(pd.DataFrame({"2025-12-31": [20]}, index=["short term debt"]), None)
        self.assertIsNone(result.metrics["total_debt"])

    def test_mismatched_currency_is_not_merged(self):
        from dataclasses import replace

        class Dollar(StubFinancialProvider):
            def fetch(self, *args, **kwargs):
                return replace(super().fetch(*args, **kwargs), currency="USD")

        chain = FinancialProviderChain(
            (StubFinancialProvider("first", {"revenue_ttm": 100}), Dollar("usd", {"equity": 50}))
        )
        result = chain.fetch("ASELS", as_of=datetime.now(UTC))
        self.assertIsNone(result.metrics.get("equity"))
        self.assertIn("usd:currency_mismatch_or_unknown", result.errors)

    def test_discrete_ttm_does_not_sum_across_missing_quarter(self):
        income = pd.DataFrame(
            {"2026-06-30": [10], "2026-03-31": [10], "2025-09-30": [10], "2025-06-30": [10]},
            index=["revenue"],
        )
        result = _snapshot_from_frames(
            provider_id="test",
            symbol="ASELS",
            as_of=datetime.now(UTC),
            balance=None,
            income=income,
            cashflow=None,
            info={},
            fast={},
        )
        self.assertIsNone(result.metrics["revenue_ttm"])

    def test_current_quote_recalculates_multiples(self):
        snapshot = StubFinancialProvider(
            "test",
            {
                "net_income_ttm": 100,
                "equity": 200,
                "net_debt": 50,
                "ebitda_ttm": 80,
                "shares_outstanding": 10,
            },
        ).fetch("ASELS", as_of=datetime.now(UTC))
        result = apply_quote(snapshot, MarketQuote("ASELS", 30, "TRY", "quote", datetime.now(UTC)))
        self.assertEqual(result.metrics["market_cap"], 300)
        self.assertEqual(result.metrics["pe"], 3)
        self.assertEqual(result.metrics["ev_ebitda"], 350 / 80)
        self.assertIsNone(result.metadata["quote_market_time"])

    def test_invalid_primary_quote_uses_fallback(self):
        class Ticker:
            def __init__(self, info):
                self.info = info

        provider = MarketQuoteProvider(
            borsapy_factory=lambda _: Ticker({"last": -1, "currency": "TRY"}),
            yfinance_factory=lambda _: Ticker(
                {"regularMarketPrice": 20, "currency": "TRY", "regularMarketTime": 1000}
            ),
        )
        self.assertEqual(provider.fetch("ASELS").source, "yfinance")
