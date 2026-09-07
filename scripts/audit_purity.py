from __future__ import annotations

import argparse
import ast
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

NETWORK_MODULES = {
    "aiohttp",
    "borsapy",
    "httpx",
    "playwright",
    "requests",
    "selenium",
    "tvDatafeed",
    "tvdatafeed",
    "urllib",
    "yfinance",
}
CLOCK_CALLS = {
    "date.today",
    "datetime.now",
    "datetime.today",
    "pd.Timestamp.now",
    "pd.Timestamp.today",
    "time.time",
}
ENV_CALLS = {"os.getenv", "os.putenv", "os.unsetenv"}
FILE_CALLS = {
    "open",
    "Path.open",
    "Path.read_bytes",
    "Path.read_text",
    "Path.write_bytes",
    "Path.write_text",
}
WRITE_CALLS = {"Path.write_bytes", "Path.write_text"}


@dataclass(frozen=True)
class Finding:
    category: str
    detail: str
    line: int
    severity: str


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


class PurityVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[Finding] = []
        self.scope_depth = 0

    def add(self, category: str, detail: str, node: ast.AST, severity: str) -> None:
        self.findings.append(
            Finding(category, detail, getattr(node, "lineno", 0), severity)
        )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope_depth += 1
        self.generic_visit(node)
        self.scope_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in NETWORK_MODULES:
                self.add("network_import", alias.name, node, "high")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root = (node.module or "").split(".", 1)[0]
        if root in NETWORK_MODULES:
            self.add("network_import", node.module or root, node, "high")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func)
        lowered = name.casefold()
        if name in CLOCK_CALLS:
            self.add("clock", name, node, "medium")
        if name in ENV_CALLS:
            self.add("environment", name, node, "medium")
        if name in FILE_CALLS:
            severity = "high" if name in WRITE_CALLS else "medium"
            self.add("file_io", name, node, severity)
        if lowered.startswith("random.") or lowered.startswith("np.random."):
            self.add("randomness", name, node, "medium")
        if any(token in lowered for token in ("sendmessage", "send_message", "sendphoto", "send_document")):
            self.add("delivery", name, node, "high")
        if any(lowered.startswith(f"{module}.") for module in NETWORK_MODULES):
            self.add("network_call", name, node, "high")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if dotted_name(node.value) == "os.environ":
            self.add("environment", "os.environ[]", node, "medium")
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if self.scope_depth == 0 and isinstance(node.value, (ast.List, ast.Dict, ast.Set)):
            targets = ",".join(dotted_name(target) for target in node.targets)
            self.add("module_mutable", targets or "assignment", node, "low")
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if self.scope_depth == 0 and isinstance(node.value, (ast.List, ast.Dict, ast.Set)):
            self.add("module_mutable", dotted_name(node.target), node, "low")
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str) and "api.telegram.org" in node.value:
            self.add("delivery", "api.telegram.org literal", node, "high")


def classification(findings: list[Finding]) -> str:
    categories = {finding.category for finding in findings}
    if categories & {"delivery", "network_call", "file_io"}:
        return "IMPURE"
    if findings:
        return "WRAPPABLE"
    return "PURE"


def audit_file(path: Path, root: Path) -> dict[str, object]:
    try:
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError) as error:
        return {
            "path": path.relative_to(root).as_posix(),
            "classification": "UNPARSEABLE",
            "error": str(error),
            "findings": [],
        }
    visitor = PurityVisitor()
    visitor.visit(tree)
    ordered = sorted(visitor.findings, key=lambda finding: (finding.line, finding.category))
    return {
        "path": path.relative_to(root).as_posix(),
        "classification": classification(ordered),
        "findings": [asdict(finding) for finding in ordered],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Legacy Python saflık adaylarını AST ile tara")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    reports = [
        audit_file(path, root)
        for path in sorted(root.rglob("*.py"))
        if ".git" not in path.parts and "__pycache__" not in path.parts
    ]
    counts = Counter(str(report["classification"]) for report in reports)
    payload = {
        "schema_version": 1,
        "root": str(root),
        "summary": dict(sorted(counts.items())),
        "files": reports,
        "notice": "Statik aday raporudur; otomatik silme veya saflık kanıtı değildir.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
