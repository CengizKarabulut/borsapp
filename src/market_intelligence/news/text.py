from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from market_intelligence.core.identity import stable_hash

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_MOJIBAKE_MARKERS = ("Ã", "Ä", "Å", "Â", "â€", "ðŸ", "ï¿½")
_TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


def _mojibake_score(value: str) -> int:
    return sum(value.count(marker) for marker in _MOJIBAKE_MARKERS)


def repair_mojibake(value: str) -> str:
    """Repair UTF-8 bytes decoded as latin-1/cp1252 without touching valid Turkish."""

    current = value
    for _ in range(2):
        score = _mojibake_score(current)
        if score == 0:
            break
        candidates = [current]
        for encoding in ("latin-1", "cp1252"):
            try:
                candidates.append(current.encode(encoding).decode("utf-8"))
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
        best = min(candidates, key=_mojibake_score)
        if _mojibake_score(best) >= score:
            break
        current = best
    return current


def normalize_news_text(value: Any, *, preserve_paragraphs: bool = False) -> str:
    text = html.unescape(str(value or ""))
    text = _TAG.sub(" ", text)
    text = repair_mojibake(text)
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    if not preserve_paragraphs:
        return " ".join(text.split())
    lines = [_SPACE.sub(" ", line).strip() for line in text.replace("\r", "").split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def sentence_excerpt(value: Any, *, max_chars: int) -> str:
    """Return a readable excerpt, preferring a complete sentence over a hard slice."""

    text = normalize_news_text(value)
    if len(text) <= max_chars:
        return text
    if max_chars < 2:
        return "…"[:max_chars]
    window = text[: max_chars - 1]
    sentence_end = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    if sentence_end >= max(60, max_chars // 3):
        return window[: sentence_end + 1].rstrip() + "…"
    word_end = window.rfind(" ")
    if word_end >= max(20, max_chars // 2):
        window = window[:word_end]
    return window.rstrip(" ,;:-") + "…"


def canonical_news_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = urlsplit(value.strip())
    except ValueError:
        return value.strip()
    host = parsed.netloc.casefold().removeprefix("www.")
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_") and key.casefold() not in _TRACKING_KEYS
        )
    )
    return urlunsplit((parsed.scheme.casefold(), host, parsed.path.rstrip("/"), query, ""))


def news_dedup_key(
    *,
    source: str,
    news_id: str,
    headline: str,
    url: str | None,
    published_at: datetime,
) -> str:
    if source == "kap" and news_id.startswith("kap:"):
        return news_id
    canonical_url = canonical_news_url(url)
    if canonical_url:
        return "url:" + stable_hash(canonical_url)
    normalized_headline = re.sub(
        r"[^a-z0-9çğıöşü]+",
        " ",
        normalize_news_text(headline).casefold(),
    ).strip()
    return "content:" + stable_hash(
        {"headline": normalized_headline, "local_date": published_at.date().isoformat()}
    )
