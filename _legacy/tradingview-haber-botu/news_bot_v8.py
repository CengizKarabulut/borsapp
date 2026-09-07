"""v8: Araştırma raporlarında sıkı tarih, içerik ve tekrar filtresi.

Amaçlar:
- Menü/sosyal medya/kurumsal sayfa linklerini rapor sanmamak.
- Tarihi güvenilir biçimde doğrulanamayan veya eski raporları Telegram'a göndermemek.
- Aynı rapor farklı URL/parametreyle görünse de tekrar göndermemek.
- Sabit bir rapor sayfası yeni tarihle güncellendiğinde yeni raporu algılayabilmek.
"""

import hashlib
import os
import re
import time
import unicodedata
from datetime import date, datetime
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests

import news_bot as base
import news_bot_v4 as v4
import news_bot_v5 as v5
import news_bot_v6 as v6
import news_bot_v7 as v7


ISTANBUL = ZoneInfo("Europe/Istanbul")
RESEARCH_MAX_AGE_DAYS = max(0, int(os.getenv("RESEARCH_MAX_AGE_DAYS", "0")))
RESEARCH_STATE_KEY = "research_reports_v8"

BLOCKED_SCHEMES = ("javascript:", "mailto:", "tel:")
BLOCKED_HOSTS = {
    "facebook.com", "www.facebook.com",
    "instagram.com", "www.instagram.com",
    "linkedin.com", "www.linkedin.com", "tr.linkedin.com",
    "twitter.com", "www.twitter.com", "x.com", "www.x.com",
    "youtube.com", "www.youtube.com",
    "whatsapp.com", "www.whatsapp.com",
}
BLOCKED_PATH_TOKENS = (
    "/iletisim", "/iletişim", "/contact", "/kariyer", "/career",
    "/gizlilik", "/privacy", "/cerez", "/çerez", "/cookie",
    "/hakkinda", "/hakkında", "/about", "/yonetim", "/yönetim",
    "/ust-yonetim", "/üst-yönetim", "/finansallar", "/ticaret-sicil",
    "/yetki-belge", "/istirak", "/iştirak", "/platform", "/destek",
    "/urunler", "/ürünler", "/bize-ulas", "/bize-ulaş",
)
GENERIC_TITLES = {
    "", "indir", "pdf", "pdf indir", "görüntüle", "goruntule", "incele",
    "detay", "detaylı oku", "detayli oku", "tıklayınız", "tiklayiniz",
    "raporu incele", "raporu indir", "devamı", "devami",
}
ONE_PER_DAY_TYPES = {
    "gunluk_bulten", "teknik_bulten", "model_portfoy", "strateji_raporu"
}

YMD_RE = re.compile(r"(?<!\d)(20\d{2})[-_./](\d{1,2})[-_./](\d{1,2})(?!\d)")
DMY_RE = re.compile(r"(?<!\d)(\d{1,2})[-_./](\d{1,2})[-_./](20\d{2})(?!\d)")
COMPACT_DMY_RE = re.compile(r"(?<!\d)(\d{2})(\d{2})(20\d{2})(?!\d)")


def clean(value):
    return base.clean(value)


def _ascii(value):
    value = clean(value).lower()
    value = "".join(
        char for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _safe_date(year, month, day):
    try:
        return date(int(year), int(month), int(day))
    except (TypeError, ValueError):
        return None


def extract_dates(value):
    """Metin/URL içinden olası tarihleri bul; sırayı koru."""
    text = clean(value)
    found = []

    for match in YMD_RE.finditer(text):
        parsed = _safe_date(match.group(1), match.group(2), match.group(3))
        if parsed and parsed not in found:
            found.append(parsed)

    for match in DMY_RE.finditer(text):
        parsed = _safe_date(match.group(3), match.group(2), match.group(1))
        if parsed and parsed not in found:
            found.append(parsed)

    for match in COMPACT_DMY_RE.finditer(text):
        parsed = _safe_date(match.group(3), match.group(2), match.group(1))
        if parsed and parsed not in found:
            found.append(parsed)

    parsed_worded = v4.parse_bulletin_date(text)
    if parsed_worded and parsed_worded not in found:
        found.append(parsed_worded)

    return found


def _canonical_report_url(item):
    return base.canonical_url(
        item.get("document_url") or item.get("page_url") or item.get("link") or ""
    )


def _is_blocked_url(url):
    raw = clean(url)
    lowered = raw.lower()
    if not raw or lowered.startswith(BLOCKED_SCHEMES) or lowered.startswith("#"):
        return True

    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host in BLOCKED_HOSTS:
        return True
    return any(token in path for token in BLOCKED_PATH_TOKENS)


def _inside_navigation(anchor):
    node = anchor
    for _ in range(5):
        node = getattr(node, "parent", None)
        if not node:
            break
        if getattr(node, "name", "") in {"nav", "header", "footer"}:
            return True
        role = clean(node.get("role")) if hasattr(node, "get") else ""
        if role.lower() in {"navigation", "banner", "contentinfo"}:
            return True
    return False


def _local_anchor_context(anchor):
    """Global menü metnini taşımadan yalnız bağlantının yakın çevresini kullan."""
    pieces = [
        clean(anchor.get_text(" ", strip=True)),
        clean(anchor.get("title")),
        clean(anchor.get("aria-label")),
    ]
    node = getattr(anchor, "parent", None)
    for _ in range(2):
        if not node or getattr(node, "name", "") in {"nav", "header", "footer"}:
            break
        text = clean(node.get_text(" ", strip=True))
        if 12 <= len(text) <= 650:
            pieces.append(text)
        node = getattr(node, "parent", None)
    return clean(" ".join(piece for piece in pieces if piece))


def _report_type_from_evidence(text, href):
    evidence = clean(f"{text} {urlparse(href).path}")
    report_type, _, label = v6.classify_report_type(evidence)
    if report_type == "arastirma":
        return None, None
    return report_type, label


def _date_from_item(item):
    """Tarih seç. URL ve metin ciddi biçimde çelişiyorsa raporu güvenilmez say."""
    url = _canonical_report_url(item)
    url_dates = extract_dates(url)

    explicit = clean(
        f"{item.get('published_date', '')} {item.get('date_text', '')} {item.get('title', '')}"
    )
    text_dates = extract_dates(explicit)

    if url_dates and text_dates:
        if not set(url_dates).intersection(text_dates):
            return None, "date_conflict"

    if text_dates:
        return text_dates[0], ""
    if url_dates:
        return url_dates[0], ""
    return None, "missing_date"


def _freshness_reason(published, today=None):
    today = today or datetime.now(ISTANBUL).date()
    if not published:
        return "missing_date"
    if published > today:
        return "future_date"
    if (today - published).days > RESEARCH_MAX_AGE_DAYS:
        return "stale_date"
    return ""


def _normalize_title(title):
    text = _ascii(title)
    text = re.sub(r"\b20\d{2}\b", " ", text)
    text = re.sub(r"\b\d{1,2}\b", " ", text)
    stop = {
        "pdf", "indir", "rapor", "raporu", "bulten", "gunluk",
        "teknik", "model", "portfoy", "strateji", "arastirma",
    }
    words = [word for word in text.split() if word not in stop]
    return " ".join(words)[:180]


def _semantic_key(item, published):
    source = item.get("source", "")
    report_type = item.get("report_type", "arastirma")
    title = _normalize_title(item.get("title", ""))
    url = _canonical_report_url(item)

    if report_type in ONE_PER_DAY_TYPES:
        seed = f"{source}|{report_type}|{published.isoformat()}"
    else:
        seed = f"{source}|{report_type}|{published.isoformat()}|{title or url}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def _exact_key(item, published):
    source = item.get("source", "")
    report_type = item.get("report_type", "arastirma")
    url = _canonical_report_url(item)
    title = _normalize_title(item.get("title", ""))
    seed = f"{source}|{report_type}|{published.isoformat()}|{url}|{title}"
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()


def normalize_candidate(item, today=None):
    """Gönderilebilir bir aday üret; sorunlu aday için (None, sebep) döndür."""
    candidate = dict(item)
    source = clean(candidate.get("source"))
    report_type = clean(candidate.get("report_type"))
    title = clean(candidate.get("title"))
    url = _canonical_report_url(candidate)

    if not source or not report_type or report_type == "arastirma":
        return None, "unknown_type"
    if not url or _is_blocked_url(url):
        return None, "blocked_url"

    published, reason = _date_from_item(candidate)
    if reason:
        return None, reason

    reason = _freshness_reason(published, today=today)
    if reason:
        return None, reason

    candidate["published_date"] = published.isoformat()
    candidate["date_text"] = candidate.get("date_text") or published.strftime("%d.%m.%Y")
    candidate["title"] = title or candidate.get("report_label") or "Araştırma Raporu"
    candidate["key"] = _exact_key(candidate, published)
    candidate["semantic_key"] = _semantic_key(candidate, published)
    return candidate, ""


def scan_research_page(source, config, session=requests):
    """Yalnız doğrudan rapor kanıtı taşıyan ve tarihli linkleri tara."""
    try:
        soup = v6._get_soup(config["url"], session)
    except Exception as exc:
        print(f"{config['label']} araştırma sayfası okunamadı: {exc}")
        return []

    found = []
    seen_urls = set()
    for anchor in soup.find_all("a", href=True):
        raw_href = clean(anchor.get("href"))
        if not raw_href:
            continue
        href = urljoin(config["url"], raw_href)
        if href in seen_urls or _is_blocked_url(href) or _inside_navigation(anchor):
            continue
        if not v5.same_public_site(config["url"], href):
            continue

        context = _local_anchor_context(anchor)
        report_type, report_label = _report_type_from_evidence(context, href)
        if not report_type:
            continue

        direct_text = clean(
            f"{anchor.get_text(' ', strip=True)} {anchor.get('title')} "
            f"{anchor.get('aria-label')} {urlparse(href).path}"
        )
        direct_type, _ = _report_type_from_evidence(direct_text, href)
        is_pdf = urlparse(href).path.lower().endswith(".pdf")
        if not direct_type and not (is_pdf and len(context) <= 350):
            continue

        date_candidates = extract_dates(direct_text)
        if not date_candidates:
            date_candidates = extract_dates(context)
        if not date_candidates:
            continue

        title = clean(anchor.get_text(" ", strip=True))
        if _ascii(title) in GENERIC_TITLES:
            title = report_label.title()

        delivery = "pdf" if is_pdf and config.get("delivery") != "link" else "link"

        item = {
            "source": source,
            "title": title or report_label.title(),
            "page_url": config["url"] if delivery == "pdf" else href,
            "document_url": href if delivery == "pdf" else "",
            "date_text": date_candidates[0].strftime("%d.%m.%Y"),
            "published_date": date_candidates[0].isoformat(),
            "render_html": False,
            "delivery": delivery,
            "report_type": report_type,
            "report_label": report_label,
        }
        normalized, reason = normalize_candidate(item)
        if normalized:
            seen_urls.add(href)
            found.append(normalized)
        else:
            print(f"{source}/{report_type}: aday atlandı ({reason}) -> {href}")

        if len(found) >= 20:
            break

    return found


def _candidate_score(item):
    score = 0
    if item.get("document_url"):
        score += 20
    if clean(item.get("title")).lower() not in GENERIC_TITLES:
        score += 8
    if item.get("published_date"):
        score += 10
    return score


def _dedupe_candidates(candidates):
    """Aynı raporun landing/PDF/alternatif link kopyalarından en iyi adayı tut."""
    by_semantic = {}
    for item in candidates:
        semantic = item.get("semantic_key")
        if not semantic:
            continue
        previous = by_semantic.get(semantic)
        if previous is None or _candidate_score(item) > _candidate_score(previous):
            by_semantic[semantic] = item
    return sorted(
        by_semantic.values(),
        key=lambda item: (
            item.get("published_date", ""),
            item.get("source", ""),
            item.get("report_type", ""),
        ),
    )


def _legacy_seen_for_today(state, item):
    """v6'dan v8'e geçişte aynı gün zaten atılmış raporu bir kez daha gönderme."""
    legacy = state.get("research_reports", {})
    source_state = legacy.get(item.get("source"), {})
    type_state = source_state.get(item.get("report_type"), {})
    sent_at = clean(type_state.get("sent_at"))
    if not sent_at:
        return False
    try:
        sent_date = datetime.fromisoformat(sent_at).astimezone(ISTANBUL).date()
    except ValueError:
        return False
    if sent_date != datetime.now(ISTANBUL).date():
        return False
    return item.get("report_type") in ONE_PER_DAY_TYPES


def send_research_reports():
    state = base.load_state()
    research_state = state.setdefault(RESEARCH_STATE_KEY, {})
    today = datetime.now(ISTANBUL).date()

    raw_candidates = []

    for item in v6.specialized_daily_items():
        normalized, reason = normalize_candidate(item, today=today)
        if normalized:
            raw_candidates.append(normalized)
        else:
            print(
                f"{item.get('source', '?')}/{item.get('report_type', '?')}: "
                f"özel aday atlandı ({reason})"
            )

    for source, config in v6.RESEARCH_PAGE_CONFIGS.items():
        raw_candidates.extend(scan_research_page(source, config))

    candidates = _dedupe_candidates(raw_candidates)

    for item in candidates:
        source = item["source"]
        report_type = item["report_type"]
        source_state = research_state.setdefault(source, {})
        type_state = source_state.setdefault(
            report_type,
            {"seen_keys": [], "seen_semantic_keys": [], "rejected_keys": []},
        )
        seen_keys = set(type_state.get("seen_keys", []))
        seen_semantic = set(type_state.get("seen_semantic_keys", []))

        if item["key"] in seen_keys or item["semantic_key"] in seen_semantic:
            continue

        if _legacy_seen_for_today(state, item):
            type_state["seen_keys"] = list(
                dict.fromkeys([item["key"]] + type_state.get("seen_keys", []))
            )[:300]
            type_state["seen_semantic_keys"] = list(
                dict.fromkeys([item["semantic_key"]] + type_state.get("seen_semantic_keys", []))
            )[:300]
            print(f"{source}/{report_type}: v6 bugün zaten gönderdi; v8 tekrarını bastırdı")
            continue

        try:
            sent = v6.send_research_item(item)
        except Exception as exc:
            print(f"Araştırma gönderimi başarısız [{source}/{report_type}]: {exc}")
            sent = False

        if not sent:
            continue

        type_state["seen_keys"] = list(
            dict.fromkeys([item["key"]] + type_state.get("seen_keys", []))
        )[:300]
        type_state["seen_semantic_keys"] = list(
            dict.fromkeys([item["semantic_key"]] + type_state.get("seen_semantic_keys", []))
        )[:300]
        type_state["last_published_date"] = item["published_date"]
        type_state["sent_at"] = datetime.now(ISTANBUL).isoformat()
        time.sleep(base.SEND_DELAY)

    base.save_state(state)


def main():
    v6.send_research_reports = send_research_reports
    v7.main()


if __name__ == "__main__":
    main()
