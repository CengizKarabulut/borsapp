import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from pathlib import Path

from market_intelligence.fundamentals.kap_archive import (
    KapArchivedFinancialProvider,
    KapFinancialArchive,
    parse_financial_report,
)


class KapFinancialTests(unittest.TestCase):
    def test_official_million_and_thousand_presentation_units(self):
        detail = json.loads(
            (Path(__file__).parent / "fixtures/kap_1656516_excerpt.json").read_text(
                encoding="utf-8"
            )
        )
        from bs4 import BeautifulSoup

        for label, scale in (("1.000.000 TL", 1000000), ("Bin TL", 1000), ("BİN TL", 1000)):
            with self.subTest(label=label):
                soup = BeautifulSoup("".join(detail["disclosureBody"]), "html.parser")
                for row in soup.select(".financial-header-table tr"):
                    cells = row.find_all("td", recursive=False)
                    if (
                        len(cells) == 2
                        and cells[0].get_text(" ", strip=True) == "Sunum Para Birimi"
                    ):
                        cells[1].string = label
                report = parse_financial_report({**detail, "disclosureBody": [str(soup)]})
                self.assertEqual(report["currency"], "TRY")
                self.assertEqual(report["scale"], scale)
                revenue = next(f for f in report["facts"] if f["concept"] == "ifrs-full_Revenue")
                self.assertEqual(revenue["value"], float(revenue["raw_value"]) * scale)

    def test_official_html_context_and_negative_cashflow(self):
        detail = json.loads(
            (Path(__file__).parent / "fixtures/kap_1656516_excerpt.json").read_text(
                encoding="utf-8"
            )
        )
        report = parse_financial_report(detail)
        self.assertEqual(report["currency"], "TRY")
        self.assertEqual(report["inflation_basis"], "report_end_purchasing_power")
        values = {(f["concept"], f["start"], f["end"]): f["value"] for f in report["facts"]}
        self.assertEqual(values[("ifrs-full_Revenue", "2026-01-01", "2026-06-30")], 2437537053)
        self.assertEqual(values[("ifrs-full_Revenue", "2026-04-01", "2026-06-30")], 1361820234)
        self.assertEqual(
            values[
                (
                    "kap-fr_PurchaseOfPropertyPlantEquipmentAndIntangibleAssetsClassifiedAsInvestingActivities",
                    "2026-01-01",
                    "2026-06-30",
                )
            ],
            -56007193,
        )

    def test_result_cap_is_not_silently_accepted(self):
        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return [{}] * 2000

        class Client:
            def post(self, *args, **kwargs):
                return Response()

        with tempfile.TemporaryDirectory() as root:
            store = KapFinancialArchive(Path(root), client=Client())
            with self.assertRaisesRegex(RuntimeError, "cap reached"):
                store.list_reports(date(2026, 1, 1), date(2026, 1, 1))

    def test_rebased_ttm_uses_latest_comparative(self):
        class Rebaser:
            def factor(self, start, end):
                return 1.1

        with tempfile.TemporaryDirectory() as root:
            provider = KapArchivedFinancialProvider(Path(root), rebaser=Rebaser())
            stamp = datetime(2026, 9, 1, tzinfo=UTC)

            def report(identifier, end, values):
                return {
                    "symbol": "ASELS",
                    "disclosure_id": identifier,
                    "report_end": end,
                    "published_at": stamp.isoformat(),
                    "observed_at": stamp.isoformat(),
                    "currency": "TRY",
                    "consolidation": "Konsolide",
                    "company_name": "Test",
                    "inflation_basis": "report_end_purchasing_power",
                    "raw_sha256": "hash",
                    "source_url": "https://www.kap.org.tr/tr/Bildirim/" + identifier,
                    "facts": [
                        {
                            "concept": "ifrs-full_Revenue",
                            "value": v,
                            "start": period[:4] + "-01-01",
                            "end": period,
                        }
                        for period, v in values.items()
                    ],
                }

            provider.store.archive.put(
                "ASELS",
                "kap",
                "report:1",
                report("1", "2025-12-31", {"2025-12-31": 200, "2025-06-30": 50}),
                observed_at=stamp,
            )
            provider.store.archive.put(
                "ASELS",
                "kap",
                "report:2",
                report("2", "2026-06-30", {"2026-06-30": 120, "2025-06-30": 90}),
                observed_at=stamp,
            )
            result = provider.fetch("ASELS", as_of=stamp)
            self.assertAlmostEqual(result.metrics["revenue_ttm"], 250)
            self.assertAlmostEqual(result.metrics["revenue_ytd_growth"], (120 / 90 - 1) * 100)

    def test_pdf_path_identifier_is_validated(self):
        with tempfile.TemporaryDirectory() as root:
            store = KapFinancialArchive(Path(root))
            with self.assertRaises(ValueError):
                store.archive_report("../../file")


class KapPdfTransportTests(unittest.TestCase):
    def test_fixed_java_byte_array_wrapper(self):
        from market_intelligence.fundamentals.kap_archive import decode_kap_pdf

        pdf = b"%PDF-1.5\ncontent"
        prefix = bytes.fromhex("aced0005757200025b42acf317f8060854e00200007870")
        wrapped = prefix + len(pdf).to_bytes(4, "big") + pdf
        self.assertEqual(decode_kap_pdf(wrapped), pdf)
        with self.assertRaises(ValueError):
            decode_kap_pdf(wrapped[:-1])
        with self.assertRaises(ValueError):
            decode_kap_pdf(b"<html>error %PDF-1.5")


class KapArchiveResilienceTests(unittest.TestCase):
    def test_rate_limit_honors_retry_after_before_retrying(self):
        class Response:
            def __init__(self, status):
                self.status_code = status
                self.headers = {"Retry-After": "120"}

            def raise_for_status(self):
                if self.status_code == 429:
                    raise RuntimeError("rate limited")

            def json(self):
                return []

        class Client:
            def __init__(self):
                self.calls = 0

            def post(self, *args, **kwargs):
                self.calls += 1
                return Response(429 if self.calls == 1 else 200)

        with tempfile.TemporaryDirectory() as folder:
            waits = []
            client = Client()
            store = KapFinancialArchive(
                Path(folder), client=client, request_interval=0, sleeper=waits.append
            )
            self.assertEqual(store.list_reports(date(2026, 1, 1), date(2026, 1, 2)), [])
            self.assertEqual(client.calls, 2)
            self.assertEqual(waits, [120])

    def test_persistent_rate_limit_has_bounded_retries(self):
        class Response:
            status_code = 429
            headers = {}

            def raise_for_status(self):
                raise RuntimeError("rate limited")

        class Client:
            def post(self, *args, **kwargs):
                return Response()

        with tempfile.TemporaryDirectory() as folder:
            waits = []
            store = KapFinancialArchive(
                Path(folder), client=Client(), request_interval=0, sleeper=waits.append
            )
            with self.assertRaisesRegex(RuntimeError, "rate limited"):
                store.list_reports(date(2026, 1, 1), date(2026, 1, 2))
            self.assertEqual(waits, [60, 120, 240])

    def test_resume_starts_after_last_completed_interval(self):
        class Store(KapFinancialArchive):
            def __init__(self, root, fail):
                super().__init__(root)
                self.fail = fail
                self.calls = []

            def list_reports(self, start, end):
                self.calls.append((start, end))
                if self.fail and start.month == 2:
                    raise RuntimeError("temporary outage")
                return []

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkpoint = root / "progress.json"
            first = Store(root, True)
            with self.assertRaisesRegex(RuntimeError, "temporary outage"):
                first.sync(
                    ("ASELS",), start=date(2026, 1, 1), end=date(2026, 2, 10), checkpoint=checkpoint
                )
            resumed = Store(root, False)
            resumed.sync(
                ("ASELS",), start=date(2026, 1, 1), end=date(2026, 2, 10), checkpoint=checkpoint
            )
            self.assertEqual(resumed.calls, [(date(2026, 2, 1), date(2026, 2, 10))])
            self.assertEqual(json.loads(checkpoint.read_text())["next_date"], "2026-02-11")

    def test_failed_document_does_not_advance_checkpoint(self):
        class Store(KapFinancialArchive):
            def list_reports(self, start, end):
                return [{"stockCodes": "ASELS", "disclosureIndex": "123"}]

            def archive_report(self, *args, **kwargs):
                raise RuntimeError("missing document")

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checkpoint = root / "progress.json"
            result = Store(root).sync(
                ("ASELS",), start=date(2026, 1, 1), end=date(2026, 2, 10), checkpoint=checkpoint
            )
            self.assertEqual(result["failed"], 1)
            self.assertFalse(checkpoint.exists())
