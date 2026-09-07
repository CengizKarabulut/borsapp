from __future__ import annotations

import argparse
import csv
import hashlib
import re
from pathlib import Path

TEXT_SUFFIXES = {
    ".cfg",
    ".csv",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
VERSIONED_NAME = re.compile(r"(?:^|[_-])v\d+(?:[_-]|\.|$)", re.IGNORECASE)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def line_count(path: Path) -> int | None:
    if path.suffix.casefold() not in TEXT_SUFFIXES:
        return None
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return sum(1 for _ in handle)
    except (OSError, UnicodeDecodeError):
        return None


def suggested_action(relative: Path) -> tuple[str, bool, str]:
    value = relative.as_posix().casefold()
    name = relative.name.casefold()
    if name in {"state.json", "news_cache.json", "telegram_offset.json"}:
        return "GÖÇ", False, "Çalışma zamanı durumu Result Store'a taşınmalı"
    if "/.github/workflows/" in f"/{value}":
        return "ARŞİV", False, "Merkezi CI/batch workflow ile karşılaştırılmalı"
    if "/tests/" in f"/{value}" or name.startswith("test_"):
        return "TAŞI", False, "Parity/golden test kaynağı"
    if VERSIONED_NAME.search(name) or "legacy" in name:
        return "ARŞİV", True, "Sürümlenmiş veya legacy dosya; erişilebilirlik doğrulanmalı"
    if "telegram" in value:
        return "BİRLEŞ", False, "Merkezi listener/publisher/outbox sınırına taşınmalı"
    if "indicator" in value:
        return "BİRLEŞ", False, "Feature implementasyonu ve parity adayı"
    if "scanner" in value or "scan" in name:
        return "BÖL", False, "Veri çekme, hesap ve teslimat sorumlulukları ayrılmalı"
    if "requirement" in name or name == "pyproject.toml":
        return "BİRLEŞ", False, "Kök bağımlılık ve lock stratejisine alınmalı"
    return "İNCELE", False, "Dosya bazlı karar gerekli"


def main() -> None:
    parser = argparse.ArgumentParser(description="Legacy dosya migration envanteri")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        relative = path.relative_to(root)
        action, dead_code_candidate, note = suggested_action(relative)
        rows.append(
            {
                "source_repo": relative.parts[0] if relative.parts else "",
                "source_path": relative.as_posix(),
                "suffix": path.suffix.casefold(),
                "bytes": path.stat().st_size,
                "lines": line_count(path),
                "sha256": sha256(path),
                "suggested_action": action,
                "dead_code_candidate": str(dead_code_candidate).lower(),
                "decision_status": "unverified",
                "target_path": "",
                "note": note,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0]) if rows else [
        "source_repo",
        "source_path",
        "suffix",
        "bytes",
        "lines",
        "sha256",
        "suggested_action",
        "dead_code_candidate",
        "decision_status",
        "target_path",
        "note",
    ]
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} dosya envantere alındı")


if __name__ == "__main__":
    main()
