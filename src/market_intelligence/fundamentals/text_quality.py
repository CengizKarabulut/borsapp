"""Provider prose, Turkish company-name and real-growth helpers."""

from __future__ import annotations

import re

TURKISH_CHARS = frozenset("çğıöşüÇĞİÖŞÜ")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)

_TR_STOPWORDS = frozenset(
    {
        "ve",
        "ile",
        "için",
        "olarak",
        "bir",
        "bu",
        "da",
        "de",
        "olan",
        "üzere",
        "şirket",
        "şirketi",
        "sanayi",
        "ticaret",
        "faaliyet",
        "hizmet",
        "sistem",
    }
)
_EN_STOPWORDS = frozenset(
    {
        "the",
        "and",
        "of",
        "in",
        "for",
        "with",
        "to",
        "is",
        "as",
        "it",
        "company",
        "provides",
        "offers",
        "operates",
        "systems",
        "services",
    }
)


def turkish_char_count(text: str) -> int:
    return sum(char in TURKISH_CHARS for char in text)


def _words(text: str) -> list[str]:
    return [word.casefold() for word in _WORD.findall(text)]


def is_probably_turkish(text: str, *, minimum_words: int = 8) -> bool | None:
    """Classify sufficiently long prose; return None when evidence is weak."""

    if not text or not text.strip():
        return None
    words = _words(text)
    if len(words) < minimum_words:
        return None
    turkish = sum(word in _TR_STOPWORDS for word in words)
    english = sum(word in _EN_STOPWORDS for word in words)
    if english >= 2 and english > turkish:
        return False
    if turkish >= 2 and turkish > english:
        return True
    character_evidence = turkish_char_count(text)
    if character_evidence >= max(2, len(words) // 6) and english == 0:
        return True
    return None


def prefer_turkish_name(*candidates: str | None) -> str | None:
    """Prefer a Turkish spelling while preserving source order on a tie."""

    available = [value.strip() for value in candidates if value and value.strip()]
    if not available:
        return None
    return max(available, key=turkish_char_count)


def guard_provider_prose(text: str | None) -> tuple[str | None, str]:
    """Return provider prose only when there is enough evidence it is Turkish."""

    if not text or not text.strip():
        return None, "sağlayıcı açıklama alanı boş"
    verdict = is_probably_turkish(text)
    if verdict is True:
        return text.strip(), "Türkçe"
    if verdict is False:
        return None, "sağlayıcı açıklaması Türkçe değil; çeviri yapılmadı"
    return None, "dil tespit edilemedi; metin kullanılmadı"


def real_growth(nominal_pct: float | None, inflation_pct: float | None) -> float | None:
    """Calculate real growth using (1 + nominal) / (1 + inflation) - 1."""

    if nominal_pct is None or inflation_pct is None or inflation_pct <= -100.0:
        return None
    return ((1.0 + nominal_pct / 100.0) / (1.0 + inflation_pct / 100.0) - 1.0) * 100.0


def growth_verdict(nominal_pct: float | None, inflation_pct: float | None) -> str:
    if nominal_pct is None:
        return "Veri yok"
    real = real_growth(nominal_pct, inflation_pct)
    if real is None:
        return f"Nominal %{nominal_pct:+.1f} · reel: TÜFE verisi yok (UNKNOWN)"
    if abs(real) < 0.05:
        direction = "reel yatay"
    else:
        direction = "reel büyüme" if real > 0 else "reel daralma"
    return (
        f"Nominal %{nominal_pct:+.1f} · TÜFE %{inflation_pct:+.1f} "
        f"→ %{real:+.1f} {direction}"
    )
