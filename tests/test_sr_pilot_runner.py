from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.run_sr_pilot import output_directory, select_on_validation, select_reference


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
                        reference=dict(source='borsapy-tradingview-0.11.0', adjustment=adjustment,
                                       row_count=rows, last_bar='2026-10-14', sha256='a' * 64))
        actual = request('2026-10-15', 'splits', 100)
        manifest = {'requests': {'actual': actual,
                                 'other': request('2026-10-16', 'splits', 500),
                                 'unproven': request('2026-10-15', 'unknown', 1000)}}
        self.assertEqual(select_reference(manifest, 'ASELS', '2026-10-15'), actual['reference'])
        with self.assertRaisesRegex(ValueError, 'verified_daily_vintage_unavailable'):
            select_reference(manifest, 'NEW', '2026-10-15')

    def test_output_cannot_overwrite_history_runtime_or_existing_results(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for directory in ('src/research', 'tools/pilot', 'config/new', 'results/exit-research/pilot'):
                with self.subTest(directory=directory):
                    with self.assertRaisesRegex(ValueError, 'output_must_not_overlap'):
                        output_directory(root / directory, root)
            output = output_directory(root / 'results/support-resistance/pilot', root)
            with self.assertRaises(FileExistsError):
                output_directory(output, root)


if __name__ == '__main__':
    unittest.main()
