from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from market_intelligence.scanning.catalog import load_scanner_catalog
from scripts.atc_export_dashboard import SCANNER_ORDER, TIMEFRAMES, export_matrix, matrix_rows, status_label

ROOT = Path(__file__).resolve().parents[1]


class AtcExportTests(unittest.TestCase):
    def test_no_match_and_no_data_are_different(self):
        self.assertEqual(status_label('no_match', ()), 'KOSUL_YOK')
        self.assertEqual(status_label('unknown', ()), 'HESAPLANAMADI')
        self.assertEqual(status_label('match', ()), 'ESLESME_YON_BELIRSIZ')
        self.assertEqual(status_label('match', ('bullish', 'bearish')), 'KARMA')
        self.assertEqual(status_label('match', ('neutral',)), 'NOTR')

    def test_report_uses_exact_runtime_calendar_hash(self):
        # Catch the production regression where 630 symbols were scanned
        # but every valid daily cell displayed SURUM_UYUSMAZLIGI.
        class StopAfterCatalog(Exception):
            pass

        with patch("scripts.atc_export_dashboard.load_scanner_catalog",
                   side_effect=StopAfterCatalog) as catalog:
            with self.assertRaises(StopAfterCatalog):
                export_matrix(None, "ATC_630", ROOT / "config/scanners.toml",
                              "unused.csv", as_of=datetime(2026, 10, 15).date())
        self.assertEqual(catalog.call_count, 1)
        self.assertTrue(catalog.call_args.kwargs["calendar_version"].startswith(
            "exchange-calendars-xist:"
        ))

    def test_complete_matrix_and_ruleset_mismatch(self):
        catalog = {b.scanner.id: b for b in load_scanner_catalog(ROOT / 'config/scanners.toml')}
        rid = SCANNER_ORDER[0]
        sample = ('id-1','1d',rid,catalog[rid].scanner.version,
                  catalog[rid].ruleset_hash,datetime(2026,10,13,15,tzinfo=UTC),
                  'match',None,'eval-1',['bullish'])
        rows = list(matrix_rows([('id-1','ASELS'),('id-2','AKBNK')],[sample],catalog))
        self.assertEqual(len(rows), 2 * len(TIMEFRAMES) * 18)
        value = next(r for r in rows if r['Hisse']=='ASELS' and r['ZamanDilimi']=='1d' and r['TaramaNo']==1)
        self.assertEqual(value['Durum'],'POZITIF')
        missing = next(r for r in rows if r['Hisse']=='AKBNK' and r['ZamanDilimi']=='1d' and r['TaramaNo']==1)
        self.assertEqual(missing['Durum'],'VERI_YOK')
        unsupported = next(r for r in rows if r['Hisse']=='ASELS' and r['ZamanDilimi']=='5m' and r['TaramaNo']==17)
        self.assertEqual(unsupported['Durum'],'DESTEKLENMIYOR')
        wrong = list(sample)
        wrong[4] = 'old_hash'
        rows2=list(matrix_rows([('id-1','ASELS')],[tuple(wrong)],catalog))
        r=next(x for x in rows2 if x['ZamanDilimi']=='1d' and x['TaramaNo']==1)
        self.assertEqual(r['Durum'],'SURUM_UYUSMAZLIGI')


if __name__ == '__main__':
    unittest.main()
