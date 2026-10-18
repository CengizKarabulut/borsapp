"""Transactional presentation-only install, using temporary E-like folders."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from scripts import e_manual_bridge

_SCRIPT = Path(__file__).parents[1] / "scripts/install_e_manual_bridge.py"
_SPEC = importlib.util.spec_from_file_location("bridge_installer_under_test", _SCRIPT)
installer = importlib.util.module_from_spec(_SPEC)
with patch.dict(sys.modules, {"e_manual_bridge": e_manual_bridge}):
    _SPEC.loader.exec_module(installer)


class ManualBridgeInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "installation"
        self.scripts = self.base / "package/scripts"
        for directory in (self.root / "tools", self.root / "data", self.root / "results",
                          self.root / "src/market_intelligence/native", self.root / "config",
                          self.scripts, self.scripts.parent / "docs"):
            directory.mkdir(parents=True)
        self.manual = self.root / "src/market_intelligence/native/manual_batch.py"
        self.manual.write_bytes(b"# frozen scanner formatter fixture\r\n")
        (self.root / "config/scanners.toml").write_bytes(b"# frozen scanner rules\r\n")
        (self.root / "config/manual-scanner-names.json").write_bytes(b'{"1":"A"}\r\n')
        self.wrapper = self.root / "tools/manual_stop_tp.py"
        self.wrapper.write_bytes(b"# previous exact presentation wrapper\r\n")
        self.support = self.root / "tools/atc_support_resistance.py"
        self.support.write_bytes(b"# previous context helper\r\n")
        self.manifest = self.root / "tools/manual-integration.json"
        self.profile = self.root / "results/profiles.json"
        self.profile.write_bytes(b'{"schema":"test-receipt-fixture","profiles":[]}\r\n')
        self.profile.with_suffix(".sha256").write_text(installer.digest(self.profile) + "\n")
        self.config = self.root / "config.json"
        self.write_config(absolute=False)
        self.bat = self.root / "Tarama-Gonder.bat"
        self.bat.write_bytes(b'@echo off\r\npython "%ROOT%\\tools\\manual_stop_tp.py" --root "%ROOT%"\r\n')
        (self.scripts / "e_manual_bridge.py").write_bytes(b"# newly tested adapter\n")
        (self.scripts / "atc_support_resistance.py").write_bytes(b"# newly tested context\n")
        (self.scripts.parent / "docs/NATIVE_E_REPO_SYNC.md").write_bytes(b"Installation guide\n")
        patches = (
            patch.object(installer, "SCRIPTS", self.scripts),
            patch.object(installer, "EXPECTED_RUNTIME_CODE_IDENTITY", installer.code_identity(self.root)),
            patch.object(installer, "EXPECTED_MANUAL_BATCH_SHA256", installer.digest(self.manual)),
            patch.object(installer, "OLD_WRAPPER_SHA", installer.digest(self.wrapper)),
        )
        for pending in patches:
            pending.start()
            self.addCleanup(pending.stop)
        self.protected = {p: p.read_bytes() for p in (
            self.config, self.profile, self.profile.with_suffix(".sha256"), self.manual, self.bat,
            self.root / "config/scanners.toml", self.root / "config/manual-scanner-names.json",
        )}
        self.previous = {p: p.read_bytes() if p.exists() else None for p in (
            self.wrapper, self.support, self.manifest, self.root / "tools/README-manual-integration.md",
        )}
        self.preview = Mock(return_value={
            "status": "preview", "symbol_count": 631, "timeframes": ["1h", "4h", "1d", "1wk"],
            "scan_numbers": list(range(1, 19)), "telegram_messages_sent": 0,
        })

    def write_config(self, *, absolute):
        body = json.dumps({
            "calibrated_exit_profiles_path": str(self.profile) if absolute else "results/profiles.json",
            "calibrated_exit_profiles_enabled": True,
            "preserve_this_setting": "exact original bytes",
        }, indent=2).replace("\n", "\r\n") + "\r\n"
        self.config.write_bytes(b"\xef\xbb\xbf" + body.encode())

    def assert_protected_unchanged(self):
        for path, original in self.protected.items():
            self.assertEqual(path.read_bytes(), original, str(path))

    def assert_previous_restored(self):
        for path, original in self.previous.items():
            if original is None:
                self.assertFalse(path.exists(), str(path))
            else:
                self.assertEqual(path.read_bytes(), original, str(path))
        self.assert_protected_unchanged()

    def test_success_copies_readbacks_backs_up_and_preserves_runtime_and_profile_bytes(self):
        outcome = installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_called_once_with(self.root.resolve())
        self.assertEqual(outcome["status"], "installed")
        self.assertTrue(outcome["trade_plans_unchanged"])
        self.assertEqual(outcome["real_orders_sent"], 0)
        self.assertEqual(outcome["telegram_messages_sent"], 0)
        backup = Path(outcome["backup"])
        self.assertTrue(backup.is_relative_to(self.root / "updates"))
        for relative, source in (
            ("tools/manual_stop_tp.py", self.scripts / "e_manual_bridge.py"),
            ("tools/atc_support_resistance.py", self.scripts / "atc_support_resistance.py"),
            ("tools/README-manual-integration.md", self.scripts.parent / "docs/NATIVE_E_REPO_SYNC.md"),
        ):
            target = self.root / relative
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(outcome["files"][relative], installer.digest(target))
        for path, raw in self.previous.items():
            if raw is not None:
                self.assertEqual((backup / "previous" / path.relative_to(self.root)).read_bytes(), raw)
        self.assertEqual(installer.json_read(backup / "installation-result.json"), outcome)
        self.assertEqual(installer.preflight(self.root)["profile_bundle_sha256"], installer.digest(self.profile))
        self.assert_protected_unchanged()

    def test_absolute_inside_root_profile_path_works_without_rewriting_config(self):
        self.write_config(absolute=True)
        self.protected[self.config] = self.config.read_bytes()
        outcome = installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(Path(outcome["profile_bundle_path"]), Path("results/profiles.json"))
        self.assert_protected_unchanged()

    def test_preview_failure_rolls_back_all_files_including_existing_manifest(self):
        self.manifest.write_bytes(b'{"previous":"manifest bytes must survive"}\r\n')
        self.previous[self.manifest] = self.manifest.read_bytes()
        self.preview.side_effect = ValueError("preview deliberately rejected")
        with self.assertRaisesRegex(ValueError, "preview deliberately rejected"):
            installer.install(self.root, preview_runner=self.preview)
        self.assert_previous_restored()
        self.assertEqual(list((self.root / "updates").rglob("installation-result.json")), [])

    def test_copy_failure_rolls_back_partly_written_target_and_already_copied_wrapper(self):
        original_copy = installer.shutil.copy2

        def failed_copy(source, target):
            if Path(source).name == "atc_support_resistance.py":
                Path(target).write_bytes(b"interrupted partial copy")
                raise OSError("simulated copy failure")
            return original_copy(source, target)

        with patch.object(installer.shutil, "copy2", side_effect=failed_copy):
            with self.assertRaisesRegex(OSError, "simulated copy failure"):
                installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_not_called()
        self.assert_previous_restored()

    def test_rollback_preserves_deployment_completed_before_lock_acquisition(self):
        original_lock = installer.scan_lock
        concurrent_helper = b"# helper deployed by an installer that finished before our lock\r\n"

        @contextmanager
        def acquire_after_deployment(root, name):
            if name == "controller":
                self.support.write_bytes(concurrent_helper)
            with original_lock(root, name):
                yield

        self.previous[self.support] = concurrent_helper
        self.preview.side_effect = ValueError("preview deliberately rejected")
        with patch.object(installer, "scan_lock", side_effect=acquire_after_deployment):
            with self.assertRaisesRegex(ValueError, "preview deliberately rejected"):
                installer.install(self.root, preview_runner=self.preview)
        self.assert_previous_restored()

    def test_file_hash_readback_failure_rolls_back_without_preview(self):
        with patch.object(installer.shutil, "copy2",
                          side_effect=lambda _source, target: Path(target).write_bytes(b"bad copy")):
            with self.assertRaisesRegex(ValueError, "installed_file_hash_mismatch"):
                installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_not_called()
        self.assert_previous_restored()

    def test_unknown_existing_wrapper_refused_before_backup_or_file_mutation(self):
        self.wrapper.write_bytes(b"unknown third-party manual wrapper")
        original = self.wrapper.read_bytes()
        with self.assertRaisesRegex(ValueError, "unrecognized_existing_manual_wrapper"):
            installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_not_called()
        self.assertEqual(self.wrapper.read_bytes(), original)
        self.assertFalse((self.root / "updates").exists())
        self.assert_protected_unchanged()

    def test_outside_root_configured_profile_path_refused(self):
        settings = installer.json_read(self.config)
        settings["calibrated_exit_profiles_path"] = str(self.base / "outside.json")
        self.config.write_text(json.dumps(settings), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside_install_root"):
            installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_not_called()
        self.assertFalse((self.root / "updates").exists())

    def test_target_symlink_escape_refused_without_touching_outside_file(self):
        outside = self.base / "outside-context.py"
        outside.write_bytes(b"outside must stay unchanged")
        self.support.unlink()
        try:
            self.support.symlink_to(outside)
        except OSError as exc:
            self.skipTest(f"Symlink creation unavailable on this host: {exc}")
        with self.assertRaisesRegex(ValueError, "outside_install_root|linked_install_target"):
            installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(outside.read_bytes(), b"outside must stay unchanged")
        self.assertEqual(self.wrapper.read_bytes(), self.previous[self.wrapper])
        self.assertFalse((self.root / "updates").exists())

    def test_parent_path_escape_refused(self):
        with self.assertRaisesRegex(ValueError, "outside_install_root"):
            installer.owned(self.root, "../outside.py")

    def test_each_active_scan_lock_refuses_install_and_releases_other_acquired_locks(self):
        for name in ("controller", "hisseler", "manual-bat"):
            with self.subTest(name=name):
                with installer.scan_lock(self.root, name):
                    with self.assertRaises(OSError):
                        installer.install(self.root, preview_runner=self.preview)
                # An unsuccessful multi-lock acquisition cannot leave a stale
                # lock on any earlier member of the acquisition order.
                with installer.scan_lock(self.root, "controller"):
                    pass
                with installer.scan_lock(self.root, "hisseler"):
                    pass
                self.assert_previous_restored()
        self.preview.assert_not_called()
        self.assertFalse((self.root / "updates").exists())

    def test_profile_receipt_change_and_frozen_runtime_change_refuse_install(self):
        with self.subTest(reason="profile receipt"):
            self.profile.with_suffix(".sha256").write_text("0" * 64)
            with self.assertRaisesRegex(ValueError, "active_profile_receipt_changed"):
                installer.install(self.root, preview_runner=self.preview)
            self.profile.with_suffix(".sha256").write_bytes(self.protected[self.profile.with_suffix(".sha256")])
        with self.subTest(reason="runtime"):
            self.manual.write_bytes(b"changed runtime formatter")
            with self.assertRaisesRegex(ValueError, "frozen_runtime_identity_changed"):
                installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_not_called()
        self.assertFalse((self.root / "updates").exists())


if __name__ == "__main__":
    unittest.main()
