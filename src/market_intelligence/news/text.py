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
_SENTENCE = re.compile(r"^(.{20,240}?[.!?])(?:\s+|$)", re.DOTALL)
_WORD = re.compile(r"[a-z0-9çğıöşü]+", re.IGNORECASE)
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


def _comparison_words(value: str) -> set[str]:
    # Provider keyword titles frequently lose Turkish dotted/dotless-I
    # information when uppercased (YNETIM versus yönetim). Identity matching
    # may fold that distinction; the text shown to the user remains untouched.
    folded = unicodedata.normalize("NFKD", value.casefold().replace("ı", "i"))
    folded = "".join(character for character in folded if not unicodedata.combining(character))
    return set(_WORD.findall(folded))


def _looks_like_fragmented_headline(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    uppercase_ratio = (
        sum(character.isupper() for character in letters) / len(letters) if letters else 0.0
    )
    return (
        _mojibake_score(value) > 0
        or (value.count(",") >= 3 and uppercase_ratio >= 0.75)
        or "\ufffd" in value
    )


def polish_news_copy(headline: Any, summary: Any) -> tuple[str, str]:
    """Repair a broken provider headline and remove headline/summary repetition.

    Some news lists publish lossy, all-uppercase keyword fragments while the
    article description contains a complete Turkish lead sentence. Promotion is
    deliberately conservative: the title must look broken and both texts must
    share enough words to describe the same story.
    """

    clean_headline = normalize_news_text(headline)
    clean_summary = normalize_news_text(summary, preserve_paragraphs=True)
    if not clean_headline or not clean_summary:
        return clean_headline, clean_summary

    compact_summary = normalize_news_text(clean_summary)
    match = _SENTENCE.match(compact_summary)
    first_sentence = match.group(1).strip() if match else ""
    if first_sentence and _looks_like_fragmented_headline(clean_headline):
        headline_words = _comparison_words(clean_headline)
        sentence_words = _comparison_words(first_sentence)
        shared_ratio = (
            len(headline_words & sentence_words) / min(len(headline_words), len(sentence_words))
            if headline_words and sentence_words
            else 0.0
        )
        if shared_ratio >= 0.45:
            clean_headline = first_sentence.rstrip(" .!?")
            compact_summary = compact_summary[match.end() :].strip()

    headline_key = normalize_news_text(clean_headline).casefold().rstrip(" .!?")
    summary_key = compact_summary.casefold()
    if headline_key and summary_key.startswith(headline_key):
        compact_summary = compact_summary[len(headline_key) :].lstrip(" .!?:;,-")
    return clean_headline, compact_summary


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
