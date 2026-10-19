from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from scripts.run_sr_pilot import (
    CAPTURE_CONTRACT,
    CAPTURE_METHOD,
    CAPTURE_SOURCE,
    FEED_CONTRACT,
    load_store,
    output_directory,
    run,
    select_on_validation,
    select_reference,
    validate_dataset_contract,
)


def side_rows(config, score, *, split='validation', contacts=60, symbols=8):
    return [dict(config=config, split=split, side=side, contact_count=contacts,
                 macro_contact_symbol_count=symbols, per_symbol_macro_lower=score)
            for side in ('support', 'resistance')]


class SupportResistancePilotRunnerTests(unittest.TestCase):
    def test_selection_cannot_use_held_out_test_outcomes(self):
        validation = side_rows('lb120-w3', .4) + side_rows('lb60-w2', .5)
        selection = select_on_validation(validation)
        poisoned_test = side_rows('lb120-w3', 1, split='test') + side_rows('lb60-w2', 0, split='test')
        self.assertEqual(select_on_validation(validation + poisoned_test), selection)
        self.assertEqual(selection['selected'], 'lb60-w2')
        self.assertFalse(selection['test_used_for_selection'])
        self.assertFalse(selection['automatic_activation'])

    def test_small_or_one_sided_validation_is_not_enough_to_choose(self):
        for rows in (side_rows('lb120-w3', .9, contacts=10),
                     side_rows('lb120-w3', .9, symbols=7),
                     side_rows('lb120-w3', .9)[:1]):
            with self.subTest(rows=rows):
                self.assertIsNone(select_on_validation(rows)['selected'])

    def test_exact_score_tie_retains_current_baseline(self):
        result = select_on_validation(side_rows('lb120-w3', .4) + side_rows('lb252-w5', .4))
        self.assertEqual(result['selected'], 'lb120-w3')

    def test_reference_cannot_silently_use_other_vintage_or_unknown_adjustment(self):
        def request(vintage, adjustment, rows):
            return dict(status='completed', symbol='ASELS', interval='1d', vintage=vintage,
                        reference=dict(source=CAPTURE_SOURCE, adjustment=adjustment,
                                       row_count=rows, last_bar='2026-10-14', sha256='a' * 64))
        def key(label, vintage='2026-10-19'):
            return label + ':contract-' + CAPTURE_CONTRACT + ':vintage-' + vintage
        actual = request('2026-10-19', 'splits', 100)
        legacy = request('2026-10-19', 'splits', 10000)
        legacy['reference']['source'] = 'borsapy-tradingview-0.11.0'
        manifest = {'requests': {key('actual'): actual,
                                 key('other', '2026-10-20'): request('2026-10-20', 'splits', 500),
                                 key('unproven'): request('2026-10-19', 'unknown', 1000),
                                 key('legacy'): legacy,
                                 'missing-contract-key': request('2026-10-19', 'splits', 20000)}}
        self.assertEqual(select_reference(manifest, 'ASELS', '2026-10-19'), actual['reference'])
        with self.assertRaisesRegex(ValueError, 'verified_daily_vintage_unavailable'):
            select_reference(manifest, 'NEW', '2026-10-19')

    def test_loaded_dataset_requires_exact_typed_corrected_feed_contract(self):
        valid = SimpleNamespace(source=CAPTURE_SOURCE, adjustment='splits',
            reference={'source': CAPTURE_SOURCE}, metadata={'source': CAPTURE_SOURCE,
                'adjustment': 'splits', 'sdk_version': '0.11.0', 'closed_only': True,
                'provenance': {'method': CAPTURE_METHOD, 'series_adjustment': 'splits',
                    'network_request': True, 'feed_contract': deepcopy(FEED_CONTRACT)}})
        validate_dataset_contract(valid)
        bad = []
        legacy_source = deepcopy(valid)
        legacy_source.source = 'borsapy-tradingview-0.11.0'
        bad.append(legacy_source)
        missing = deepcopy(valid)
        del missing.metadata['provenance']['feed_contract']
        bad.append(missing)
        for key, value in (('adjust', False), ('adjust', 1), ('auto_adjust', True)):
            item = deepcopy(valid)
            item.metadata['provenance']['feed_contract']['history_parameters'][key] = value
            bad.append(item)
        nominal = deepcopy(valid)
        nominal.metadata['provenance']['method'] = 'pinned-sdk-history-explicit-start'
        bad.append(nominal)
        for item in bad:
            with self.subTest(item=item):
                with self.assertRaisesRegex(ValueError, 'corrected_v2_history_contract_required'):
                    validate_dataset_contract(item)

    def test_readonly_forensic_default_keeps_legacy_but_pilot_requests_corrected_store(self):
        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'src/market_intelligence/research/history_store.py'
            source.parent.mkdir(parents=True)
            source.write_text('class HistoryStore: pass\n', encoding='utf-8')
            legacy, _ = load_store(root)
            corrected, _ = load_store(root, corrected=True)
            self.assertEqual(legacy.directory, root / 'results/exit-research/history')
            self.assertEqual(corrected.directory, root / 'results/exit-research-adjusted-v2/history')
            self.assertFalse(legacy.directory.exists())
            self.assertFalse(corrected.directory.exists())
            with patch('scripts.run_sr_pilot.load_store', side_effect=ValueError('stop_before_inputs')) as reader:
                with self.assertRaisesRegex(ValueError, 'stop_before_inputs'):
                    run(root, root / 'unused-output')
            reader.assert_called_once_with(root, corrected=True)

    def test_output_cannot_overwrite_history_runtime_or_existing_results(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for directory in ('src/research', 'tools/pilot', 'config/new', 'results/exit-research/pilot',
                              'results/exit-research-adjusted-v2/pilot'):
                with self.subTest(directory=directory):
                    with self.assertRaisesRegex(ValueError, 'output_must_not_overlap'):
                        output_directory(root / directory, root)
            output = output_directory(root / 'results/support-resistance/pilot', root)
            with self.assertRaises(FileExistsError):
                output_directory(output, root)


if __name__ == '__main__':
    unittest.main()
