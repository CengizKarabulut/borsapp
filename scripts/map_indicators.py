from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

TOKENS = {
    "adx",
    "alma",
    "atr",
    "bollinger",
    "cci",
    "donchian",
    "ema",
    "hma",
    "kama",
    "keltner",
    "macd",
    "obv",
    "parabolic",
    "rsi",
    "rvol",
    "sar",
    "sma",
    "smi",
    "stoch",
    "supertrend",
    "vwap",
    "vwma",
    "wma",
}


@dataclass(frozen=True)
class IndicatorCandidate:
    path: str
    line: int
    kind: str
    name: str
    indicator_tokens: tuple[str, ...]
    parameters: dict[str, Any]


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return ast.unparse(node) if hasattr(ast, "unparse") else "<dynamic>"


def matching_tokens(name: str) -> tuple[str, ...]:
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    words = set(re.findall(r"[a-z0-9]+", separated.casefold()))
    return tuple(sorted(TOKENS & words))


def inspect_file(path: Path, root: Path) -> list[IndicatorCandidate]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []

    found: list[IndicatorCandidate] = []
    relative = path.relative_to(root).as_posix()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            tokens = matching_tokens(node.name)
            if tokens:
                defaults = [None] * (len(node.args.args) - len(node.args.defaults))
                defaults.extend(literal(default) for default in node.args.defaults)
                parameters = {
                    argument.arg: default
                    for argument, default in zip(node.args.args, defaults, strict=True)
                }
                found.append(
                    IndicatorCandidate(
                        relative,
                        node.lineno,
                        "definition",
                        node.name,
                        tokens,
                        parameters,
                    )
                )
        elif isinstance(node, ast.Call):
            name = dotted_name(node.func)
            tokens = matching_tokens(name)
            if tokens:
                parameters = {
                    f"arg_{index}": literal(argument)
                    for index, argument in enumerate(node.args)
                }
                parameters.update(
                    {
                        keyword.arg or "**": literal(keyword.value)
                        for keyword in node.keywords
                    }
                )
                found.append(
                    IndicatorCandidate(
                        relative,
                        node.lineno,
                        "call",
                        name,
                        tokens,
                        parameters,
                    )
                )
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description="Legacy indikatör tanım ve çağrı adayları")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    candidates: list[IndicatorCandidate] = []
    for path in sorted(root.rglob("*.py")):
        if ".git" not in path.parts and "__pycache__" not in path.parts:
            candidates.extend(inspect_file(path, root))

    counts = Counter(
        token for candidate in candidates for token in candidate.indicator_tokens
    )
    payload = {
        "schema_version": 1,
        "root": str(root),
        "summary": dict(sorted(counts.items())),
        "candidates": [asdict(candidate) for candidate in candidates],
        "notice": "İsim tabanlı statik aday haritasıdır; formül parity kanıtı değildir.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
