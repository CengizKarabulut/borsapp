"""High-impact frozen-runtime migration, only in temporary E-like folders."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from scripts import install_e_history_basis as installer


class HistoryBasisInstallerTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix="atc-basis-installer-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.root = self.base / "fake-installation"
        self.scripts = self.base / "reviewed-package/scripts"
        self.assets = self.scripts / "e_runtime_basis_v2"
        for directory in (self.root / "tools", self.root / "data", self.root / "config",
                          self.root / "src/market_intelligence/native",
                          self.root / "src/market_intelligence/research",
                          self.root / "results/exit-research/history", self.assets,
                          self.scripts.parent / "docs"):
            directory.mkdir(parents=True)
        self.market = self.root / "src/market_intelligence/native/market_data.py"
        self.history = self.root / "src/market_intelligence/research/history_store.py"
        self.market.write_bytes(b"# known original market data fixture\r\n")
        self.history.write_bytes(b"# known original immutable history fixture\r\n")
        self.manual = self.root / "src/market_intelligence/native/manual_batch.py"
        self.manual.write_bytes(b"# frozen formatter does not change\r\n")
        self.scanners = self.root / "config/scanners.toml"
        self.names = self.root / "config/manual-scanner-names.json"
        self.scanners.write_bytes(b"# scanner formula identity fixture\r\n")
        self.names.write_bytes(b'{"1":"A"}\r\n')
        self.wrapper = self.root / "tools/manual_stop_tp.py"
        self.wrapper.write_bytes(b"# original recognized wrapper\r\n")
        self.doc = self.root / "tools/README-manual-integration.md"
        self.doc.write_bytes(b"Previous integration guide\r\n")
        self.support = self.root / "tools/atc_support_resistance.py"
        self.support.write_bytes(b"# context helper remains untouched\r\n")
        self.manifest = self.root / "tools/manual-integration.json"
        self.manifest.write_bytes((json.dumps({
            "schema": 1, "version": "recognized-pre-migration-fixture",
            "files": {"tools/manual_stop_tp.py": installer.bridge.digest(self.wrapper),
                      "tools/atc_support_resistance.py": installer.bridge.digest(self.support)},
            "preserve_manifest_field": "prior deployment metadata",
        }, indent=2) + "\r\n").encode())
        self.profile = self.root / "results/old-profiles.json"
        self.profile.write_bytes(b'{"legacy_untrusted_profile_fixture":true,"profiles":[]}\r\n')
        self.profile_receipt = self.profile.with_suffix(".sha256")
        self.profile_receipt.write_bytes((installer.bridge.digest(self.profile) + "\r\n").encode())
        self.config = self.root / "config.json"
        self.write_config(False)
        self.old_history = self.root / "results/exit-research/history/legacy-object.json"
        self.old_history.write_bytes(b'{"old_raw_basis":"preserve without retagging"}\r\n')
        self.bat = self.root / "Tarama-Gonder.bat"
        self.bat.write_bytes(b'@echo off\r\npython "%ROOT%\\tools\\manual_stop_tp.py" --root "%ROOT%"\r\n')

        self.new_files = {
            "src/market_intelligence/native/market_data.py": b"# explicitly adjusted market capture v2\n",
            "src/market_intelligence/research/history_store.py": b"# separate typed history provenance v2\n",
        }
        self.before_identity = installer.bridge.code_identity(self.root)
        old_pair = {relative: (self.root / relative).read_bytes() for relative in self.new_files}
        for relative, raw in self.new_files.items():
            (self.root / relative).write_bytes(raw)
        self.after_identity = installer.bridge.code_identity(self.root)
        for relative, raw in old_pair.items():
            (self.root / relative).write_bytes(raw)
        self.package = {
            "schema": 1, "before_runtime_identity": self.before_identity,
            "after_runtime_identity": self.after_identity, "files": {},
        }
        for relative, asset_name in installer.SOURCE_FILES.items():
            asset = self.assets / asset_name
            asset.write_bytes(self.new_files[relative])
            self.package["files"][relative] = {
                "before_sha256": installer.bridge.digest(self.root / relative),
                "after_sha256": installer.bridge.digest(asset),
            }
        self.review_manifest = self.assets / "review-manifest.json"
        self.review_manifest.write_text(json.dumps(self.package), encoding="utf-8")
        (self.scripts / "e_manual_bridge.py").write_bytes(b"# wrapper bound to reviewed new identity\n")
        (self.scripts.parent / "docs/NATIVE_E_REPO_SYNC.md").write_bytes(b"Updated migration guide\n")
        for pending in (
            patch.object(installer, "ASSETS", self.assets),
            patch.object(installer.bridge, "SCRIPTS", self.scripts),
            patch.object(installer.bridge, "EXPECTED_RUNTIME_CODE_IDENTITY", self.after_identity),
        ):
            pending.start()
            self.addCleanup(pending.stop)
        self.original = {path: path.read_bytes() for path in (
            self.market, self.history, self.wrapper, self.doc, self.manifest,
            self.config, self.profile, self.profile_receipt, self.support, self.old_history,
            self.manual, self.scanners, self.names, self.bat,
        )}
        self.protected = {path: raw for path, raw in self.original.items()
                          if path not in (self.market, self.history, self.wrapper, self.doc, self.manifest)}
        self.preview = Mock(return_value={
            "status": "preview", "symbol_count": 631,
            "timeframes": ["1h", "4h", "1d", "1wk"],
            "scan_numbers": list(range(1, 19)), "telegram_messages_sent": 0,
        })

    def write_config(self, enabled, *, absolute_profile=False):
        settings = {
            "calibrated_exit_profiles_enabled": enabled,
            "calibrated_exit_profiles_path": str(self.profile) if absolute_profile else "results/old-profiles.json",
            "preserve_unknown_setting": {"some_value": "same BOM and line endings"},
        }
        self.config.write_bytes(b"\xef\xbb\xbf" + (json.dumps(settings, indent=2)
                                                 .replace("\n", "\r\n") + "\r\n").encode())

    def assert_preserved(self):
        for path, expected in self.protected.items():
            self.assertEqual(path.read_bytes(), expected, str(path))

    def assert_all_restored(self):
        for path, expected in self.original.items():
            self.assertEqual(path.read_bytes(), expected, str(path))
        self.assertEqual(installer.bridge.code_identity(self.root), self.before_identity)
        self.assertEqual(list(self.root.rglob("*.basis-install.tmp")), [])

    def assert_no_backup(self):
        self.assertFalse((self.root / "updates").exists())
        self.preview.assert_not_called()

    def test_success_requires_exact_pair_and_identity_and_preserves_untrusted_objects(self):
        receipt = installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_called_once_with(self.root)
        self.assertEqual(receipt["runtime_identity"], self.after_identity)
        self.assertNotEqual(receipt["runtime_identity"], self.before_identity)
        self.assertEqual(receipt["status"], "installed")
        self.assertFalse(receipt["calibration_enabled"])
        self.assertFalse(receipt["profiles_revalidated"])
        self.assertEqual(receipt["old_history_objects_modified"], 0)
        self.assertEqual(receipt["telegram_messages_sent"], 0)
        self.assertEqual(receipt["orders_sent"], 0)
        for relative, expected in self.new_files.items():
            self.assertEqual((self.root / relative).read_bytes(), expected)
        backup = Path(receipt["backup"])
        self.assertTrue(backup.is_relative_to(self.root / "updates"))
        for path in (self.market, self.history, self.wrapper, self.doc, self.manifest):
            self.assertEqual((backup / "previous" / path.relative_to(self.root)).read_bytes(), self.original[path])
        self.assertEqual(installer.bridge.json_read(backup / "installation-result.json"), receipt)
        manifest = installer.bridge.json_read(self.manifest)
        self.assertEqual(manifest["preserve_manifest_field"], "prior deployment metadata")
        self.assertEqual(manifest["calibration_status"], "quarantined_untrusted_legacy_history_basis")
        self.assertFalse(manifest["legacy_history_reused"])
        self.assertEqual(manifest["new_research_store_required"], "results/exit-research-adjusted-v2/history")
        self.assertEqual(installer.verify(self.root, self.package)["runtime_identity"], self.after_identity)
        self.assert_preserved()

    def test_only_explicit_false_calibration_is_accepted_before_any_mutation(self):
        for value in (True, None, 0, "false", ""):
            with self.subTest(value=value):
                self.write_config(value)
                before = self.config.read_bytes()
                with self.assertRaisesRegex(ValueError, "disable_untrusted_calibration"):
                    installer.install(self.root, preview_runner=self.preview)
                self.assertEqual(self.config.read_bytes(), before)
                self.assertEqual(self.market.read_bytes(), self.original[self.market])
                self.assertEqual(self.history.read_bytes(), self.original[self.history])
                self.assert_no_backup()

    def test_absolute_profile_inside_installation_keeps_original_config_bytes(self):
        self.write_config(False, absolute_profile=True)
        self.protected[self.config] = self.config.read_bytes()
        receipt = installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(Path(receipt["profile_bundle_path"]), Path("results/old-profiles.json"))
        self.assert_preserved()

    def test_profile_receipt_mismatch_cannot_be_repaired_or_revalidated_implicitly(self):
        self.profile_receipt.write_bytes(b"0" * 64)
        before = self.profile.read_bytes()
        with self.assertRaisesRegex(ValueError, "preserved_profile_receipt_mismatch"):
            installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(self.profile.read_bytes(), before)
        self.assertEqual(self.profile_receipt.read_bytes(), b"0" * 64)
        self.assert_no_backup()

    def test_unknown_runtime_rejected_even_when_two_patch_targets_still_match(self):
        self.manual.write_bytes(b"# unrelated runtime formula modified\n")
        with self.assertRaisesRegex(ValueError, "unreviewed_runtime"):
            installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(self.market.read_bytes(), self.original[self.market])
        self.assertEqual(self.history.read_bytes(), self.original[self.history])
        self.assert_no_backup()

    def test_exact_original_pair_checked_independently_of_global_identity(self):
        self.history.write_bytes(b"# unexpected history implementation\n")
        with patch.object(installer.bridge, "code_identity", return_value=self.before_identity):
            with self.assertRaisesRegex(ValueError, "unreviewed_source"):
                installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(self.market.read_bytes(), self.original[self.market])
        self.assertEqual(self.history.read_bytes(), b"# unexpected history implementation\n")
        self.assert_no_backup()

    def test_unrecognized_existing_wrapper_is_not_overwritten(self):
        self.wrapper.write_bytes(b"# unknown third-party wrapper\n")
        with self.assertRaisesRegex(ValueError, "unrecognized_wrapper"):
            installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(self.wrapper.read_bytes(), b"# unknown third-party wrapper\n")
        self.assert_no_backup()

    def test_failure_after_sources_rolls_back_pair_wrapper_document_and_manifest(self):
        seen = []

        def fail(phase):
            seen.append(phase)
            self.assertEqual(installer.bridge.code_identity(self.root), self.after_identity)
            self.assertEqual(self.wrapper.read_bytes(), (self.scripts / "e_manual_bridge.py").read_bytes())
            raise RuntimeError("source-stage failure fixture")

        with self.assertRaisesRegex(RuntimeError, "source-stage failure"):
            installer.install(self.root, preview_runner=self.preview, fault=fail)
        self.assertEqual(seen, ["after_sources"])
        self.preview.assert_not_called()
        self.assert_all_restored()
        self.assertEqual(list((self.root / "updates").rglob("installation-result.json")), [])

    def test_preview_failure_restores_existing_manifest_and_source_bytes(self):
        def fail(_root):
            manifest = installer.bridge.json_read(self.manifest)
            self.assertEqual(manifest["version"], installer.VERSION)
            self.assertEqual(installer.bridge.code_identity(self.root), self.after_identity)
            raise ValueError("no-scan preview fixture failed")

        self.preview.side_effect = fail
        with self.assertRaisesRegex(ValueError, "preview fixture failed"):
            installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_called_once()
        self.assert_all_restored()
        self.assertEqual(list((self.root / "updates").rglob("installation-result.json")), [])

    def test_corrupted_target_after_copy_is_detected_and_rolled_back(self):
        def corrupt(_phase):
            self.market.write_bytes(b"# corruption after a successful copy\n")

        with self.assertRaisesRegex(ValueError, "installed_basis_source_mismatch"):
            installer.install(self.root, preview_runner=self.preview, fault=corrupt)
        self.preview.assert_not_called()
        self.assert_all_restored()
        self.assertEqual(list((self.root / "updates").rglob("installation-result.json")), [])

    def test_interrupted_temporary_copy_rolls_back_already_copied_source(self):
        original_replace = Path.replace

        def fail_history_replace(path, target):
            if path.name == "history_store.py.basis-install.tmp":
                raise OSError("temporary replacement failed")
            return original_replace(path, target)

        with patch.object(Path, "replace", new=fail_history_replace):
            with self.assertRaisesRegex(OSError, "replacement failed"):
                installer.install(self.root, preview_runner=self.preview)
        self.preview.assert_not_called()
        self.assert_all_restored()

    def test_asset_change_before_review_blocks_all_installation(self):
        asset = self.assets / installer.SOURCE_FILES["src/market_intelligence/native/market_data.py"]
        asset.write_bytes(b"# candidate source changed after review\n")
        with self.assertRaisesRegex(ValueError, "basis_patch_asset_changed"):
            installer.install(self.root, preview_runner=self.preview)
        self.assert_all_restored()
        self.assert_no_backup()

    def test_after_identity_must_be_the_wrappers_expected_identity(self):
        self.package["after_runtime_identity"] = "d" * 64
        self.review_manifest.write_text(json.dumps(self.package), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "wrapper_and_basis_patch_identity_mismatch"):
            installer.install(self.root, preview_runner=self.preview)
        self.assert_all_restored()
        self.assert_no_backup()

    def test_extra_manifest_target_refused_before_touching_installation(self):
        self.package["files"]["src/market_intelligence/extra.py"] = {
            "before_sha256": "a" * 64, "after_sha256": "b" * 64,
        }
        self.review_manifest.write_text(json.dumps(self.package), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unexpected_basis_patch_inventory"):
            installer.install(self.root, preview_runner=self.preview)
        self.assert_all_restored()
        self.assert_no_backup()

    def test_all_four_live_locks_refuse_and_release_partial_acquisitions(self):
        for name in ("controller", "hisseler", "manual-bat", "exit-research"):
            with self.subTest(name=name):
                with installer.bridge.scan_lock(self.root, name):
                    with self.assertRaises(OSError):
                        installer.install(self.root, preview_runner=self.preview)
                for earlier in ("controller", "hisseler", "manual-bat", "exit-research"):
                    with installer.bridge.scan_lock(self.root, earlier):
                        pass
                self.assert_all_restored()
                self.assert_no_backup()

    def test_linked_source_parent_is_refused_even_when_hashes_match(self):
        original_is_symlink = Path.is_symlink
        linked_parent = self.root / "src/market_intelligence/native"

        def marked_link(path):
            return path == linked_parent or original_is_symlink(path)

        with patch.object(Path, "is_symlink", new=marked_link):
            with self.assertRaisesRegex(ValueError, "linked_install_target"):
                installer.install(self.root, preview_runner=self.preview)
        self.assert_all_restored()
        self.assert_no_backup()

    def test_profile_path_cannot_escape_the_selected_installation(self):
        settings = installer.bridge.json_read(self.config)
        settings["calibrated_exit_profiles_path"] = "../outside-profiles.json"
        self.config.write_text(json.dumps(settings), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside_install_root|active_profile_outside"):
            installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(self.profile.read_bytes(), self.original[self.profile])
        self.assert_no_backup()

    def test_physical_source_symlink_escape_never_writes_external_target(self):
        outside = self.base / "outside-market-data.py"
        outside.write_bytes(self.original[self.market])
        self.market.unlink()
        try:
            self.market.symlink_to(outside)
        except OSError as exc:
            self.market.write_bytes(self.original[self.market])
            self.skipTest(f"Host cannot create a real symlink: {exc}")
        with self.assertRaisesRegex(ValueError, "outside_install_root|linked_install_target"):
            installer.install(self.root, preview_runner=self.preview)
        self.assertEqual(outside.read_bytes(), self.original[self.market])
        self.assert_no_backup()

    def test_final_verifier_rejects_any_reverted_half_or_wrapper(self):
        installer.install(self.root, preview_runner=self.preview)
        self.history.write_bytes(self.original[self.history])
        with self.assertRaisesRegex(ValueError, "installed_basis_source_mismatch"):
            installer.verify(self.root, self.package)
        self.history.write_bytes(self.new_files["src/market_intelligence/research/history_store.py"])
        self.manual.write_bytes(b"# unrelated formula changed after install\n")
        with self.assertRaisesRegex(ValueError, "installed_basis_runtime_mismatch"):
            installer.verify(self.root, self.package)
        self.manual.write_bytes(self.original[self.manual])
        self.wrapper.write_bytes(self.original[self.wrapper])
        with self.assertRaisesRegex(ValueError, "installed_basis_wrapper_mismatch"):
            installer.verify(self.root, self.package)
        self.assert_preserved()


class ActualReviewedHistoryBasisPackageTests(unittest.TestCase):
    def test_real_repository_assets_match_reviewed_inventory_identity_and_python_syntax(self):
        # Read package assets only; importing/executing the frozen E runtime
        # would contaminate the upstream interpreter and is intentionally avoided.
        manifest = installer.reviewed_package()
        self.assertEqual(set(manifest["files"]), set(installer.SOURCE_FILES))
        self.assertEqual(len(manifest["files"]), 2)
        self.assertNotEqual(manifest["before_runtime_identity"], manifest["after_runtime_identity"])
        self.assertEqual(manifest["after_runtime_identity"], installer.bridge.EXPECTED_RUNTIME_CODE_IDENTITY)
        for relative, asset_name in installer.SOURCE_FILES.items():
            asset = installer.ASSETS / asset_name
            self.assertRegex(manifest["files"][relative]["before_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(manifest["files"][relative]["after_sha256"], r"^[0-9a-f]{64}$")
            compile(asset.read_text(encoding="utf-8-sig"), str(asset), "exec")


if __name__ == "__main__":
    unittest.main()
