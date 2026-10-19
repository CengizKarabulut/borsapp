"""Install a reviewed correction to the separate frozen E data runtime.

Old history and profiles are preserved, never relabeled. Calibration must be
explicitly disabled before installation. No download, scan, message or order.
"""
from __future__ import annotations

import argparse
import json
import uuid
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from . import install_e_manual_bridge as bridge
else:
    import install_e_manual_bridge as bridge

ASSETS = Path(__file__).resolve().parent / "e_runtime_basis_v2"
SOURCE_FILES = {
    "src/market_intelligence/native/market_data.py": "market_data.py.txt",
    "src/market_intelligence/research/history_store.py": "history_store.py.txt",
}
VERSION = "e-history-adjustment-basis-v2-20261019"


def reviewed_package():
    manifest = bridge.json_read(ASSETS / "review-manifest.json")
    if set(manifest["files"]) != set(SOURCE_FILES):
        raise ValueError("unexpected_basis_patch_inventory")
    for relative, asset in SOURCE_FILES.items():
        if manifest["files"][relative]["after_sha256"] != bridge.digest(ASSETS / asset):
            raise ValueError("basis_patch_asset_changed")
    if manifest["after_runtime_identity"] != bridge.EXPECTED_RUNTIME_CODE_IDENTITY:
        raise ValueError("wrapper_and_basis_patch_identity_mismatch")
    return manifest


def _preserved(root):
    config = bridge.owned(root, "config.json")
    raw = config.read_bytes()
    settings = json.loads(raw.decode("utf-8-sig"))
    if settings.get("calibrated_exit_profiles_enabled") is not False:
        raise ValueError("disable_untrusted_calibration_before_basis_install")
    relative = Path(settings["calibrated_exit_profiles_path"])
    if relative.is_absolute():
        try:
            relative = relative.relative_to(root)
        except ValueError:
            raise ValueError("preserved_profile_outside_install_root") from None
    profile = bridge.owned(root, relative)
    profile_hash = bridge.digest(profile)
    if profile.with_suffix(".sha256").read_text().strip() != profile_hash:
        raise ValueError("preserved_profile_receipt_mismatch")
    return {"config_sha256": bridge.digest(config), "profile_bundle_sha256": profile_hash,
            "profile_bundle_path": str(profile.relative_to(root)),
            "calibration_enabled": False}


def verify(root, package):
    root = Path(root).resolve(strict=True)
    for relative in SOURCE_FILES:
        if bridge.digest(bridge.owned(root, relative)) != package["files"][relative]["after_sha256"]:
            raise ValueError("installed_basis_source_mismatch")
    identity = bridge.code_identity(root)
    if identity != package["after_runtime_identity"]:
        raise ValueError("installed_basis_runtime_mismatch")
    if bridge.digest(root / "tools/manual_stop_tp.py") != bridge.digest(bridge.SCRIPTS / "e_manual_bridge.py"):
        raise ValueError("installed_basis_wrapper_mismatch")
    return {"runtime_identity": identity, **_preserved(root)}


def install(root, *, preview_runner=bridge.preview_installed, fault=None):
    root = Path(root).resolve(strict=True)
    package = reviewed_package()
    with ExitStack() as locks:
        for name in ("controller", "hisseler", "manual-bat", "exit-research"):
            locks.enter_context(bridge.scan_lock(root, name))
        preserved = _preserved(root)
        if bridge.code_identity(root) != package["before_runtime_identity"]:
            raise ValueError("unreviewed_runtime_before_basis_install")
        for relative in SOURCE_FILES:
            if bridge.digest(bridge.owned(root, relative)) != package["files"][relative]["before_sha256"]:
                raise ValueError("unreviewed_source_before_basis_install")
        previous_manifest = bridge.json_read(root / "tools/manual-integration.json")
        wrapper = bridge.owned(root, "tools/manual_stop_tp.py")
        if bridge.digest(wrapper) != previous_manifest["files"]["tools/manual_stop_tp.py"]:
            raise ValueError("unrecognized_wrapper_before_basis_install")
        sources = {relative: ASSETS / asset for relative, asset in SOURCE_FILES.items()}
        sources["tools/manual_stop_tp.py"] = bridge.SCRIPTS / "e_manual_bridge.py"
        sources["tools/README-manual-integration.md"] = bridge.SCRIPTS.parent / "docs/NATIVE_E_REPO_SYNC.md"
        targets = {name: bridge.owned(root, name) for name in sources}
        targets["tools/manual-integration.json"] = bridge.owned(root, "tools/manual-integration.json")
        previous = {name: path.read_bytes() for name, path in targets.items()}
        backup = bridge.owned(root, "updates/history-basis-" + datetime.now().strftime("%Y%m%d-%H%M%S")
                              + "-" + uuid.uuid4().hex[:8])
        backup.mkdir(parents=True, exist_ok=False)
        for name, raw in previous.items():
            saved = backup / "previous" / name
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes(raw)
        changed = []
        try:
            for name, source in sources.items():
                changed.append(name)
                temporary = targets[name].with_name(targets[name].name + ".basis-install.tmp")
                try:
                    temporary.write_bytes(source.read_bytes())
                    temporary.replace(targets[name])
                finally:
                    temporary.unlink(missing_ok=True)
                if bridge.digest(targets[name]) != bridge.digest(source):
                    raise ValueError("basis_install_copy_verification_failed")
            if fault:
                fault("after_sources")
            after = verify(root, package)
            if any(after[key] != value for key, value in preserved.items()):
                raise ValueError("basis_install_changed_preserved_config_or_profiles")
            manifest = {**previous_manifest, **after, "version": VERSION,
                        "installed_at": datetime.now(UTC).isoformat(),
                        "calibration_status": "quarantined_untrusted_legacy_history_basis",
                        "legacy_history_reused": False,
                        "new_research_store_required": "results/exit-research-adjusted-v2/history",
                        "files": {**previous_manifest["files"],
                                  **{name: bridge.digest(path) for name, path in targets.items()
                                     if name != "tools/manual-integration.json"}}}
            changed.append("tools/manual-integration.json")
            targets["tools/manual-integration.json"].write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            preview = preview_runner(root)
            verify(root, package)
            if _preserved(root) != preserved:
                raise ValueError("basis_install_changed_preserved_config_or_profiles")
            receipt = {"schema": 1, "version": VERSION, "status": "installed", **after,
                       "backup": str(backup), "preview": preview,
                       "old_history_objects_modified": 0, "profiles_revalidated": False,
                       "telegram_messages_sent": 0, "orders_sent": 0,
                       "files": {name: bridge.digest(path) for name, path in targets.items()}}
            (backup / "installation-result.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
            return receipt
        except BaseException:
            for name in reversed(changed):
                targets[name].write_bytes(previous[name])
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("E:/Borsapp-Manual"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    result = verify(args.root, reviewed_package()) if args.verify_only else install(args.root)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
