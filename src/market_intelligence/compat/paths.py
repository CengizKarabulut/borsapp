from __future__ import annotations

import os
from pathlib import Path


def repository_root() -> Path:
    """Locate checked-out runtime assets in source, wheel and container installs."""
    candidates: list[Path] = []
    configured = os.environ.get("BORSAPP_REPOSITORY_ROOT", "").strip()
    if configured:
        candidates.append(Path(configured))
    candidates.append(Path.cwd())
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / "_legacy").is_dir() and (candidate / "config").is_dir():
            return candidate
    raise RuntimeError(
        "Borsapp repo kökü bulunamadı; BORSAPP_REPOSITORY_ROOT değerini ayarlayın"
    )

