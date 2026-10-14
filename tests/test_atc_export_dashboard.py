from __future__ import annotations

import unittest
from datetime import UTC, datetime
from pathlib import Path

from market_intelligence.scanning.catalog import load_scanner_catalog
from scripts.atc_export_dashboard import SCANNER_ORDER, TIMEFRAMES, matrix_rows, status_label

ROOT = Path(__file__).resolve().parents[1]


class AtcExportTests(unittest.TestCase):
    def test_no_match_and_no_data_are_different(self):
        self.assertEqual(status_label('no_match', ()), 'KOSUL_YOK')
        self.assertEqual(status_label('unknown', ()), 'HESAPLANAMADI')
        self.assertEqual(status_label('match', ()), 'ESLESME_YON_BELIRSIZ')
        self.assertEqual(status_label('match', ('bullish', 'bearish')), 'KARMA')
        self.assertEqual(status_label('match', ('neutral',)), 'NOTR')

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
