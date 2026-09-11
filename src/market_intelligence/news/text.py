from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from market_intelligence.core.identity import stable_hash

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


class _NewsHTMLText(HTMLParser):
    """Extract copy without executing markup or retaining script/style bodies."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden.append(tag)
        if not self.hidden and tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n\n")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden:
            if tag == self.hidden[-1]:
                self.hidden.pop()
            return
        if tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def normalize_news_text(value: Any, *, preserve_paragraphs: bool = False) -> str:
    text = str(value or "")
    # RSS descriptions sometimes contain twice-escaped HTML.
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    parser = _NewsHTMLText()
    parser.feed(text)
    parser.close()
    text = repair_mojibake("".join(parser.parts))
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    if not preserve_paragraphs:
        return " ".join(text.split())
    lines = [_SPACE.sub(" ", line).strip() for line in text.replace("\r", "").split("\n")]
    return _BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def combine_news_paragraphs(*values: Any) -> str:
    """Merge repeated RSS leads, metadata and article paragraphs once, in order."""

    paragraphs: list[str] = []
    for value in values:
        for paragraph in normalize_news_text(value, preserve_paragraphs=True).split("\n\n"):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            key = normalize_news_text(paragraph).casefold()
            if any(key in normalize_news_text(existing).casefold() for existing in paragraphs):
                continue
            contained = [
                index for index, existing in enumerate(paragraphs)
                if normalize_news_text(existing).casefold() in key
            ]
            if contained:
                paragraphs[contained[0]] = paragraph
                for index in reversed(contained[1:]):
                    paragraphs.pop(index)
            else:
                paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


def sentence_excerpt(
    value: Any, *, max_chars: int, preserve_paragraphs: bool = False
) -> str:
    """Return a readable excerpt, preferring a complete sentence over a hard slice."""

    text = normalize_news_text(value, preserve_paragraphs=preserve_paragraphs)
    if len(text) <= max_chars:
        return text
    if max_chars < 2:
        return "…"[:max_chars]
    window = text[: max_chars - 1]
    endings = list(re.finditer(r"[.!?](?=\s|$)", window))
    sentence_end = endings[-1].start() if endings else -1
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


    if not (first_sentence and _looks_like_fragmented_headline(normalize_news_text(headline))):
        compact_summary = clean_summary
    # Only remove a complete headline prefix: "Kâr arttı" must not delete
    # the beginning of "Kâr arttırıldı". Regex matching avoids casefold offsets
    # changing the slice position for Turkish dotted I.
    pattern = re.escape(clean_headline.rstrip(" .!?"))
    pattern = pattern.replace(r"\ ", r"\s+")
    if pattern:
        prefix = re.compile(r"^" + pattern + r"(?=$|[\s.!?:;,—–-])", re.IGNORECASE)
        for _ in range(3):
            match = prefix.match(compact_summary)
            if match is None:
                break
            compact_summary = compact_summary[match.end():].lstrip(" \n.!?:;,—–-")
    return clean_headline, combine_news_paragraphs(compact_summary)



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
