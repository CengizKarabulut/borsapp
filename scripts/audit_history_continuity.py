"""Flag unreconciled price boundaries without altering or auto-adjusting history."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from .run_sr_pilot import (
        digest,
        load_store,
        output_directory,
        protect_state,
        read_json,
        write_csv,
    )
else:
    from run_sr_pilot import (
        digest,
        load_store,
        output_directory,
        protect_state,
        read_json,
        write_csv,
    )


def boundaries(rows, threshold=.30):
    return [dict(index=index, timestamp=rows[index]['timestamp'],
                 previous_close=rows[index - 1]['close'], opening=rows[index]['open'],
                 overnight_fraction=rows[index]['open'] / rows[index - 1]['close'] - 1)
            for index in range(1, len(rows))
            if abs(rows[index]['open'] / rows[index - 1]['close'] - 1) > threshold]


def run(root, output, vintage='2026-10-15'):
    root = Path(root).resolve(strict=True)
    store, reader = load_store(root)
    before = protect_state(root)
    manifest_path = store.directory / 'manifest.json'
    manifest = read_json(manifest_path)
    profiles = read_json(root / 'results/exit-research/calibration-active-CAL-20261018.json')['profiles']
    active_sources = {profile['provenance']['history_sha256'] for profile in profiles}
    references = {}
    for request in manifest['requests'].values():
        ref = request.get('reference', {})
        if (request.get('status') != 'completed' or request.get('vintage') != vintage
                or ref.get('source') != 'borsapy-tradingview-0.11.0' or ref.get('adjustment') != 'splits'):
            continue
        if ref['interval'] == '1d' or ref['sha256'] in active_sources:
            key = ref['symbol'], ref['interval']
            if key not in references or ref['row_count'] > references[key]['row_count']:
                references[key] = ref
    output = output_directory(output, root)
    datasets, flags, errors = [], [], []
    for (symbol, interval), reference in sorted(references.items()):
        try:
            path = store.directory / reference['path']
            before_hash = digest(path)
            data = store.load(reference)
            found = boundaries(data.rows)
            if digest(path) != before_hash:
                raise ValueError('source_changed_during_audit')
            active_ids = [profile['profile_id'] for profile in profiles
                          if profile['provenance']['history_sha256'] == reference['sha256']]
            datasets.append(dict(symbol=symbol, interval=interval, reference=reference,
                                 compressed_sha256=before_hash,
                                 full_history_flags=len(found),
                                 last600_flags=sum(row['index'] >= len(data.rows) - 600 for row in found),
                                 last252_flags=sum(row['index'] >= len(data.rows) - 252 for row in found),
                                 active_profile_ids_same_source=active_ids))
            flags.extend(dict(symbol=symbol, interval=interval, source_sha256=reference['sha256'],
                              in_last600=row['index'] >= len(data.rows) - 600,
                              in_last252=row['index'] >= len(data.rows) - 252, **row) for row in found)
        except (ValueError, OSError) as error:
            errors.append(dict(symbol=symbol, interval=interval, code=type(error).__name__))
    after = protect_state(root)
    if after != before:
        raise ValueError('protected_runtime_changed_during_audit')
    daily = [item for item in datasets if item['interval'] == '1d']
    result = dict(schema='price-continuity-review-v1', observed_at=datetime.now(UTC).isoformat(),
                  vintage=vintage, threshold_fraction=.30,
                  history_reader=reader, manifest_sha256=digest(manifest_path),
                  daily_histories_verified=len(daily),
                  daily_any_flags=sum(item['full_history_flags'] > 0 for item in daily),
                  daily_last600_flagged=sum(item['last600_flags'] > 0 for item in daily),
                  daily_last252_flagged=sum(item['last252_flags'] > 0 for item in daily),
                  active_source_histories_checked=sum(bool(item['active_profile_ids_same_source']) for item in datasets),
                  active_profiles_same_source_with_flags=sum(len(item['active_profile_ids_same_source'])
                                                             for item in datasets if item['full_history_flags']),
                  datasets=datasets, flags=flags, errors=errors,
                  protected_state_before=before, protected_state_after=after,
                  automatic_adjustments=0, profile_changes=0, network_requests=0,
                  limitations=['Threshold flags are investigation evidence, not proof of a split/error.',
                               'Matching a profile source with a boundary is not proof its train/test events crossed it.',
                               'No original row or profile was modified; further publication requires quality review.'])
    path = output / 'audit.json'
    path.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    path.with_suffix('.sha256').write_text(digest(path) + '\n', encoding='ascii')
    write_csv(output / 'boundaries.csv', flags)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.root, args.output)
    print(json.dumps({key: result[key] for key in (
        'daily_histories_verified', 'daily_any_flags', 'daily_last600_flagged',
        'daily_last252_flagged', 'active_profiles_same_source_with_flags', 'errors')}))


if __name__ == '__main__':
    main()
