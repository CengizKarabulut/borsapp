"""Read-only, prespecified support/resistance pilot on verified E daily archives.

This evaluates level reactions, not executable trades or net investment returns.
It never fetches prices, runs scanners, activates profiles, or sends messages.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__:
    from .atc_sr_evaluation import CONFIGS, Bar, Protocol, evaluate_symbol, summarize
else:
    from atc_sr_evaluation import CONFIGS, Bar, Protocol, evaluate_symbol, summarize

SYMBOLS = (
    'ASELS', 'AKBNK', 'THYAO', 'TUPRS', 'EREGL', 'BIMAS', 'MGROS', 'KCHOL',
    'SISE', 'SASA', 'AKSA', 'LOGO', 'MAVI', 'GESAN', 'ALFAS', 'HRKET',
)
IST = ZoneInfo('Europe/Istanbul')
BASELINE = 'lb120-w3'


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def load_store(root):
    """Use the actual installed immutable object reader without mkdir/init."""
    path = root / 'src/market_intelligence/research/history_store.py'
    spec = importlib.util.spec_from_file_location('sr_pilot_installed_history_store', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    store = module.HistoryStore.__new__(module.HistoryStore)
    store.directory = root / 'results/exit-research/history'
    store.objects = store.directory / 'objects'
    return store, {'file': str(path), 'sha256': digest(path)}


def select_reference(manifest, symbol, vintage):
    references = [request['reference'] for request in manifest['requests'].values()
                  if request.get('status') == 'completed' and request.get('symbol') == symbol
                  and request.get('interval') == '1d' and request.get('vintage') == vintage
                  and request.get('reference', {}).get('source') == 'borsapy-tradingview-0.11.0'
                  and request.get('reference', {}).get('adjustment') == 'splits']
    if not references:
        raise ValueError('verified_daily_vintage_unavailable:' + symbol)
    # Within a fixed vintage choose the longest independently hash-verified
    # capture, without splicing sources or silently taking legacy raw data.
    return max(references, key=lambda ref: (ref['row_count'], ref['last_bar'], ref['sha256']))


def protect_state(root):
    files = sorted((root / 'src/market_intelligence').rglob('*.py'))
    files += [root / 'config/scanners.toml', root / 'config/manual-scanner-names.json']
    identity = sha256(json.dumps([(str(p.relative_to(root)), digest(p)) for p in files],
                                 separators=(',', ':')).encode()).hexdigest()
    integration = read_json(root / 'tools/manual-integration.json')
    bundle = (root / integration['profile_bundle_path']).resolve(strict=True)
    if not bundle.is_relative_to(root):
        raise ValueError('profile_path_outside_root')
    return {'runtime_identity': identity, 'config_sha256': digest(root / 'config.json'),
            'active_bundle_sha256': digest(bundle),
            'manual_wrapper_sha256': digest(root / 'tools/manual_stop_tp.py')}


def select_on_validation(rows, baseline=BASELINE):
    """Test outcomes are inaccessible to parameter selection by construction.

    Macro rates keep long histories from dominating; both sides and at least
    eight symbols/100 contacts are required. Selection is exploratory only.
    """
    groups = defaultdict(list)
    for row in rows:
        if row['split'] == 'validation':
            groups[row['config']].append(row)
    eligible = []
    for config, sides in groups.items():
        if len(sides) != 2 or any(row['contact_count'] < 20 for row in sides):
            continue
        if sum(row['contact_count'] for row in sides) < 100:
            continue
        if any(row['macro_contact_symbol_count'] < 8 for row in sides):
            continue
        score = sum(row['per_symbol_macro_lower'] for row in sides) / 2
        eligible.append((score, config == baseline, config))
    if not eligible:
        return {'status': 'insufficient_validation_contacts', 'selected': None,
                'test_used_for_selection': False, 'automatic_activation': False}
    score, _, selected = max(eligible)
    return {'status': 'validation_only_selection_frozen_before_test_summary',
            'selected': selected, 'score': score,
            'test_used_for_selection': False, 'automatic_activation': False,
            'score_definition': 'mean_support_resistance_symbol_macro_conservative_reaction_fraction'}


def output_directory(path, root):
    output = Path(path).resolve()
    forbidden = [root / name for name in ('src', 'config', 'tools', 'results/exit-research')]
    if any(output == base or output.is_relative_to(base) for base in forbidden):
        raise ValueError('output_must_not_overlap_protected_runtime_or_existing_research')
    output.mkdir(parents=True, exist_ok=False)
    return output


def write_csv(path, rows):
    if not rows:
        return
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(root, output, *, vintage='2026-10-15', symbols=SYMBOLS):
    root = Path(root).resolve(strict=True)
    store, reader = load_store(root)
    before = protect_state(root)
    manifest_path = store.directory / 'manifest.json'
    manifest = read_json(manifest_path)
    output = output_directory(output, root)
    protocol = Protocol()
    protocol_record = {
        'schema': 'sr-pilot-prespecified-v1', 'created_at': datetime.now(UTC).isoformat(),
        'symbols': list(symbols), 'vintage': vintage, 'timeframe': '1d',
        'configs': [config.id for config in CONFIGS], 'baseline': BASELINE,
        'common_warmup': 252, 'anchor_stride': 21, 'first_contact_window_bars': 10,
        'reaction_window_after_contact_bars': 10, 'target_atr': 1.0, 'break_atr': 0.5,
        'validation_start': '2022-10-01', 'test_start': '2024-10-01',
        'fit_selection': 'validation_macro_both_sides_only_min100_contacts_8symbols',
        'nearest_level_only': True, 'spacing_optimization_tested': False,
        'freeze_level_and_atr_at_anchor': True, 'common_full_future_window_required': True,
        'continuity_guard_overnight_fraction': .30,
        'continuity_guard_scope': 'common252_history_plus20_outcome_bars_quality_censoring_not_signal',
        'costs_or_fills_modeled': False, 'selection_survivorship_bias': True,
        'sample_is_current_universe_purposive_panel_not_all631': True,
        'automatic_activation': False,
    }
    # Written before evaluating any outcome, preserving the actual protocol.
    protocol_path = output / 'protocol.json'
    protocol_path.write_text(json.dumps(protocol_record, indent=2) + '\n', encoding='utf-8')
    events, inputs, exclusions = [], [], []
    source_objects = {}
    for symbol in symbols:
        try:
            reference = select_reference(manifest, symbol, vintage)
            path = store.directory / reference['path']
            object_sha = digest(path)
            dataset = store.load(reference)
            if not dataset.metadata.get('closed_only') or dataset.adjustment != 'splits':
                raise ValueError('closed_split_history_required')
            bars = []
            for row in dataset.rows:
                stamp = datetime.fromisoformat(row['timestamp']).astimezone(IST)
                closed = stamp.replace(hour=18, minute=0, second=0, microsecond=0)
                bars.append(Bar(closed, *(row[key] for key in ('open', 'high', 'low', 'close', 'volume'))))
            result = evaluate_symbol(tuple(bars), symbol, protocol=protocol)
            events.extend(result['events'])
            source_objects[path] = object_sha
            inputs.append({'symbol': symbol, 'reference': reference,
                           'compressed_object_sha256': object_sha,
                           'received_at': dataset.metadata['received_at'],
                           'history_exhaustion': dataset.metadata['history_exhaustion'],
                           'audit': result['audit']})
            print(f'{symbol}: {len(bars)} daily bars; {len(result["events"])} evaluations', flush=True)
        except (ValueError, OSError, KeyError) as error:
            exclusions.append({'symbol': symbol, 'reason': str(error)})
    # Freeze selection from validation rows BEFORE computing test summaries.
    validation = summarize([event for event in events if event['split'] == 'validation'])
    selection = select_on_validation(validation)
    (output / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n', encoding='utf-8')
    summary = summarize(events)
    per_symbol = [dict(row, symbol=symbol) for symbol in symbols
                  for row in summarize([event for event in events if event['symbol'] == symbol])]
    after = protect_state(root)
    if after != before or any(digest(path) != value for path, value in source_objects.items()):
        raise ValueError('protected_input_or_runtime_changed_during_pilot')
    report = {
        'schema': 'sr-pilot-result-v1', 'created_at': datetime.now(UTC).isoformat(),
        'protocol': protocol_record, 'protocol_sha256': digest(protocol_path),
        'history_manifest_sha256': digest(manifest_path), 'history_reader': reader,
        'evaluation_code_sha256': digest(Path(__file__).with_name('atc_sr_evaluation.py')),
        'runner_sha256': digest(__file__), 'selection': selection,
        'symbols_requested': len(symbols), 'symbols_evaluated': len(inputs),
        'inputs': inputs, 'exclusions': exclusions, 'summary': summary,
        'protected_state_before': before, 'protected_state_after': after,
        'source_objects_unchanged': True, 'production_changes': False,
        'messages_sent': 0, 'orders_sent': 0, 'network_requests': 0,
        'limitations': [
            'Purposive sixteen-stock current-universe daily pilot; not full-market validation.',
            'OHLC contact/reaction counts are not fills, net returns, live-feed or broker equivalence.',
            'Touch-bar target-side extreme is not credited; same-bar barrier order is ambiguous.',
            'No fees/slippage modeled because no trading-return claim is made.',
            'Nearest-only evaluation cannot assess 1% versus ATR spacing of second/third levels.',
            'A validation-selected candidate is exploratory; no parameters are activated.',
            'Provider revisions and current-universe survivorship remain limitations.',
            'Windows crossing >30% overnight open/previous-close changes are censored for quality review; no price is adjusted.',
        ],
    }
    path = output / 'report.json'
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    path.with_suffix('.sha256').write_text(digest(path) + '\n', encoding='ascii')
    write_csv(output / 'summary.csv', summary)
    write_csv(output / 'per-symbol.csv', per_symbol)
    write_csv(output / 'events.csv', events)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vintage', default='2026-10-15')
    args = parser.parse_args()
    if os.name == 'nt':
        import ctypes
        # One temporary low-priority process; existing two-worker research keeps
        # its priority and lifetime. No settings or persistent jobs are changed.
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.SetPriorityClass.restype = ctypes.c_int
        if not kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x4000):
            raise OSError(ctypes.get_last_error(), 'could_not_set_temporary_low_priority')
    report = run(args.root, args.output, vintage=args.vintage)
    print(json.dumps({'output': str(args.output), 'evaluated': report['symbols_evaluated'],
                      'selection': report['selection']}))


if __name__ == '__main__':
    main()
