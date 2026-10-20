"""Install only the E presentation/context extension; preserve calibrated runtime."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import uuid
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

if __package__:
    from .e_manual_bridge import (
        EXPECTED_MANUAL_BATCH_SHA256,
        EXPECTED_RUNTIME_CODE_IDENTITY,
        VERSION,
    )
else:
    from e_manual_bridge import (
        EXPECTED_MANUAL_BATCH_SHA256,
        EXPECTED_RUNTIME_CODE_IDENTITY,
        VERSION,
    )

SCRIPTS = Path(__file__).resolve().parent
OLD_WRAPPER_SHA = '8f738a8ac93539c53c515bbb031f32949d475140cfe2fe3ea228db571eff3ad5'


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def json_read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def code_identity(root):
    files = sorted((root / 'src/market_intelligence').rglob('*.py'))
    files += [root / 'config/scanners.toml', root / 'config/manual-scanner-names.json']
    return sha256(json.dumps([(str(p.relative_to(root)), digest(p)) for p in files],
                             separators=(',', ':')).encode()).hexdigest()


def owned(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or not path.resolve().is_relative_to(root):
        raise ValueError('outside_install_root')
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('linked_install_target')
    return path


def preflight(root):
    root = Path(root).resolve(strict=True)
    identity = code_identity(root)
    if identity != EXPECTED_RUNTIME_CODE_IDENTITY:
        raise ValueError('frozen_runtime_identity_changed')
    if digest(root / 'src/market_intelligence/native/manual_batch.py') != EXPECTED_MANUAL_BATCH_SHA256:
        raise ValueError('frozen_manual_formatter_changed')
    settings = json_read(root / 'config.json')
    configured = Path(settings['calibrated_exit_profiles_path'])
    if configured.is_absolute():
        try:
            configured = configured.relative_to(root)
        except ValueError:
            raise ValueError('active_profile_outside_install_root') from None
    bundle = owned(root, configured)
    bundle_sha = digest(bundle)
    enabled = settings.get('calibrated_exit_profiles_enabled')
    if (type(enabled) is not bool
            or bundle.with_suffix('.sha256').read_text().strip() != bundle_sha):
        raise ValueError('active_profile_receipt_changed')
    wrapper = owned(root, 'tools/manual_stop_tp.py')
    if digest(wrapper) != OLD_WRAPPER_SHA:
        manifest_path = owned(root, 'tools/manual-integration.json')
        if not manifest_path.is_file():
            raise ValueError('unrecognized_existing_manual_wrapper')
        previous = json_read(manifest_path)
        if digest(wrapper) != previous['files']['tools/manual_stop_tp.py']:
            raise ValueError('unrecognized_existing_manual_wrapper')
    if 'tools\\manual_stop_tp.py" --root' not in (root / 'Tarama-Gonder.bat').read_text(encoding='utf-8-sig'):
        raise ValueError('manual_batch_entrypoint_changed')
    return {'runtime_identity': identity, 'config_sha256': digest(root / 'config.json'),
            'calibration_enabled': enabled,
            'profile_bundle_path': str(bundle.relative_to(root)), 'profile_bundle_sha256': bundle_sha}


@contextmanager
def scan_lock(root, name):
    # Same files and byte-range protocol as the frozen native process_lock.
    path = owned(root, 'data/' + name + '.lock')
    with path.open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def preview_installed(root):
    command = [str(root / '.venv/Scripts/python.exe'), '-B', str(root / 'tools/manual_stop_tp.py'),
               '--root', str(root), 'manual-batch', '--preview']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8',
                            errors='replace', timeout=180,
                            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    if result.returncode:
        raise ValueError('installed_no_scan_preview_failed')
    document = json.loads(result.stdout)
    if document.get('status') != 'preview' or document.get('real_submission') is not False:
        raise ValueError('unexpected_preview_result')
    return {'status': document['status'], 'symbol_count': document['symbol_count'],
            'timeframes': document['timeframes'], 'scan_numbers': document['scan_numbers'],
            'telegram_messages_sent': 0}


def install(root, *, preview_runner=preview_installed):
    root = Path(root).resolve(strict=True)
    before = preflight(root)
    sources = {
        'tools/manual_stop_tp.py': SCRIPTS / 'e_manual_bridge.py',
        'tools/atc_support_resistance.py': SCRIPTS / 'atc_support_resistance.py',
        'tools/atc_pivot_ladder.py': SCRIPTS / 'atc_pivot_ladder.py',
        'tools/README-manual-integration.md': SCRIPTS.parent / 'docs/NATIVE_E_REPO_SYNC.md',
    }
    targets = {relative: owned(root, relative) for relative in sources}
    targets['tools/manual-integration.json'] = owned(root, 'tools/manual-integration.json')
    with ExitStack() as stack:
        for name in ('controller', 'hisseler', 'manual-bat'):
            stack.enter_context(scan_lock(root, name))
        if preflight(root) != before:
            raise ValueError('runtime_changed_before_install')
        # Another installer may have completed after the first preflight.
        # Snapshot only while holding every lock, so rollback preserves that
        # completed deployment rather than restoring stale pre-lock bytes.
        previous = {name: path.read_bytes() if path.is_file() else None for name, path in targets.items()}
        backup = owned(root, 'updates/manual-integration-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8])
        backup.mkdir(parents=True, exist_ok=False)
        for name, raw in previous.items():
            if raw is not None:
                target = backup / 'previous' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(raw)
        changed = []
        try:
            for name, source in sources.items():
                changed.append(name)
                targets[name].parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, targets[name])
                if digest(source) != digest(targets[name]):
                    raise ValueError('installed_file_hash_mismatch')
            manifest = {'schema': 1, 'version': VERSION, 'repository': 'https://github.com/CengizKarabulut/borsapp',
                        'installed_at': datetime.now(UTC).isoformat(), **before,
                        'files': {name: digest(path) for name, path in targets.items() if name in sources},
                        'support_resistance_role': 'confirmed_structure_context_only',
                        'pivot_ladder_role': 'traditional_reference_context_only',
                        'pivot_reference_basis': 'last_completed_timeframe_bar',
                        'trade_plans_unchanged': True, 'real_orders_sent': 0, 'telegram_messages_sent': 0}
            changed.append('tools/manual-integration.json')
            targets['tools/manual-integration.json'].write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
            preview = preview_runner(root)
            if preflight(root) != before:
                raise ValueError('frozen_runtime_or_profiles_changed')
            receipt = {**manifest, 'status': 'installed', 'backup': str(backup), 'preview': preview,
                       'files': {name: digest(path) for name, path in targets.items()}}
            (backup / 'installation-result.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
            return receipt
        except BaseException:
            for name in reversed(changed):
                if previous[name] is None:
                    targets[name].unlink(missing_ok=True)
                else:
                    targets[name].write_bytes(previous[name])
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('E:/Borsapp-Manual'))
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if args.verify_only:
        preflight(args.root)
        print('E runtime and active profile receipts verified; nothing installed.')
    else:
        outcome = install(args.root)
        print(json.dumps({k: outcome[k] for k in ('status', 'version', 'backup', 'preview')}))


if __name__ == '__main__':
    main()
