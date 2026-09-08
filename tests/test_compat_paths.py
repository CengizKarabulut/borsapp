from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from market_intelligence.compat.paths import repository_root


class RepositoryRootTests(unittest.TestCase):
    def test_explicit_runtime_root_supports_installed_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "_legacy").mkdir()
            (root / "config").mkdir()
            with patch.dict(
                "os.environ",
                {"BORSAPP_REPOSITORY_ROOT": str(root)},
            ):
                self.assertEqual(repository_root(), root)

    def test_checkout_working_directory_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "_legacy").mkdir()
            (root / "config").mkdir()
            with (
                patch.dict("os.environ", {}, clear=True),
                patch("pathlib.Path.cwd", return_value=root),
            ):
                self.assertEqual(repository_root(), root)


if __name__ == "__main__":
    unittest.main()
