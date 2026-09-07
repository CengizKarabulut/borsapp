from __future__ import annotations

import ast
import unittest
from pathlib import Path

FORBIDDEN_ROOT_IMPORTS = {
    "aiohttp",
    "borsapy",
    "httpx",
    "requests",
    "telegram",
    "tvdatafeed",
    "yfinance",
}


class ArchitectureTests(unittest.TestCase):
    def test_scanning_domain_has_no_provider_or_delivery_imports(self) -> None:
        root = Path(__file__).parents[1] / "src" / "market_intelligence" / "scanning"
        violations: list[str] = []
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                module = ""
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        module = alias.name.split(".", 1)[0].casefold()
                        if module in FORBIDDEN_ROOT_IMPORTS:
                            violations.append(f"{path}:{node.lineno}:{module}")
                elif isinstance(node, ast.ImportFrom):
                    module = (node.module or "").split(".", 1)[0].casefold()
                    if module in FORBIDDEN_ROOT_IMPORTS:
                        violations.append(f"{path}:{node.lineno}:{module}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
