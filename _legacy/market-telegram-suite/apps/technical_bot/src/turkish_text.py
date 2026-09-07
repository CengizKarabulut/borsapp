"""Small Turkish-aware text normalization helpers for user-facing copy."""

from __future__ import annotations

_TR_LOWER_MAP = str.maketrans({"I": "ı", "İ": "i"})


def tr_lower(text: str) -> str:
    """Return lowercase text using Turkish I/İ rules before Unicode lowering."""
    return text.translate(_TR_LOWER_MAP).lower()
