"""Aracı kurum PDF'lerinden güvenli, extractive ve rapor türüne özel kısa özet üretir.

Bu modül dışarıdan bir LLM/API gerektirmez. Yalnız PDF içinde gerçekten bulunan metni
okur ve finansal alanları/önemli satırları seçer; veri uydurmaz.
"""

import re
from collections import Counter

from pypdf import PdfReader


TICKER_RE = re.compile(r"\b[A-Z]{3,6}\b")
TICKER_STOP = {
    "BIST", "BIST100", "MODEL", "PORTFOY", "PORTF", "HEDEF", "FIYAT", "FİYAT",
    "TAVSIYE", "TAVSİYE", "ONERI", "ÖNERİ", "ENDEKS", "TEKNIK", "TEKNİK",
    "DESTEK", "DIRENC", "DİRENÇ", "STOP", "ZARAR", "KAR", "KÂR", "AL", "SAT",
    "TUT", "TRY", "TL", "USD", "EUR", "VIOP", "VADEL", "RAPOR", "GUNLUK",
    "GÜNLÜK", "STRATEJI", "STRATEJİ", "SIRKET", "ŞİRKET", "YATIRIM", "YATIRIMCI",
    "KAP", "TCMB", "TUIK", "TÜİK", "SPK", "ROE", "FAVOK", "FAVÖK", "NET",
    "BUY", "SELL", "HOLD", "TARGET", "PRICE", "REPORT", "DAILY",
}

FINANCE_HINTS = (
    "hedef", "potansiyel", "öneri", "oneri", "tavsiye", "ağırlık", "agirlik",
    "destek", "direnç", "direnc", "stop", "zarar kes", "portföy", "portfoy",
    "kapanış", "kapanis", "fiyat", "getiri", "bist", "teknik", "%",
)


COMPANY_PATTERNS = {
    "Öneri": (
        r"(?:öneri|oneri|tavsiye)\s*[:\-]?\s*(AL|TUT|SAT|Endeks\s+Üzeri|Endeks\s+Altı|Endekse\s+Paralel)",
        r"(?:recommendation)\s*[:\-]?\s*(BUY|HOLD|SELL)",
    ),
    "Hedef fiyat": (
        r"(?:hedef\s+fiyat|target\s+price)\s*[:\-]?\s*(?:TL|TRY)?\s*(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:TL|TRY)?",
    ),
    "Getiri potansiyeli": (
        r"(?:getiri\s+potansiyeli|yükseliş\s+potansiyeli|yukselis\s+potansiyeli|upside)\s*[:\-]?\s*%?\s*(-?\d{1,3}(?:[.,]\d+)?)\s*%?",
    ),
}


KEYWORDS = {
    "teknik_bulten": (
        "destek", "direnç", "direnc", "hedef", "stop", "zarar kes", "trend",
        "kırılım", "kirilim", "momentum", "hacim", "bist 100", "bist100",
    ),
    "strateji_raporu": (
        "bist 100", "bist100", "destek", "direnç", "direnc", "risk", "faiz",
        "enflasyon", "kur", "dolar", "endeks", "beklenti", "strateji", "yabancı",
    ),
    "gunluk_bulten": (
        "bist 100", "bist100", "destek", "direnç", "direnc", "küresel", "kuresel",
        "faiz", "enflasyon", "dolar", "endeks", "beklenti", "gündem", "gundem",
    ),
    "sirket_raporu": (
        "hedef fiyat", "potansiyel", "öneri", "oneri", "tavsiye", "favök", "favok",
        "net kar", "net kâr", "ciro", "marj", "büyüme", "buyume", "risk",
    ),
    "model_portfoy": (
        "model portföy", "model portfoy", "hedef fiyat", "potansiyel", "ağırlık",
        "agirlik", "getiri", "öneri", "oneri",
    ),
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def extract_pdf_text(path, max_pages=12, max_chars=60000):
    """PDF metnini sınırlı sayfa/karakter ile çıkar; boş sayfaları atla."""
    reader = PdfReader(path)
    chunks = []
    total = 0
    for page in reader.pages[:max(1, int(max_pages))]:
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        text = text.replace("\x00", " ").strip()
        if not text:
            continue
        remaining = max_chars - total
        if remaining <= 0:
            break
        chunks.append(text[:remaining])
        total += min(len(text), remaining)
    return "\n".join(chunks)


def _lines(text):
    result, seen = [], set()
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = clean(raw).strip("•·-| ")
        if len(line) < 8 or len(line) > 380:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(line)
    return result


def _ticker_candidates(text):
    counts = Counter()
    for line in _lines(text):
        lowered = line.lower()
        finance_context = any(hint in lowered for hint in FINANCE_HINTS)
        tokens = TICKER_RE.findall(line)
        if not tokens:
            continue
        for token in tokens:
            if token in TICKER_STOP or token.isdigit():
                continue
            # Tablo satırlarında ticker genellikle kısa satırda; uzun metinde ise finansal bağlam ararız.
            if len(line) <= 120 or finance_context:
                counts[token] += 1
    return [token for token, _ in counts.most_common(24)]


def _first_field(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
        if match:
            return clean(match.group(1))
    return ""


def _key_lines(text, report_type, limit=4):
    keywords = KEYWORDS.get(report_type, KEYWORDS["gunluk_bulten"])
    ranked = []
    for index, line in enumerate(_lines(text)):
        lowered = line.lower()
        if len(line) < 24:
            continue
        hits = sum(1 for keyword in keywords if keyword in lowered)
        if hits == 0:
            continue
        score = hits * 5
        if re.search(r"\d", line):
            score += 2
        if TICKER_RE.search(line):
            score += 2
        if len(line) <= 190:
            score += 1
        ranked.append((score, -index, line))
    ranked.sort(reverse=True)
    result = []
    for _, _, line in ranked:
        short = line if len(line) <= 210 else line[:207].rstrip() + "…"
        if short not in result:
            result.append(short)
        if len(result) >= limit:
            break
    return result


def summarize_report_text(text, report_type, previous_tickers=None, max_bullets=5):
    """Rapor metninden kısa maddeler ve saklanabilir metadata döndürür."""
    text = str(text or "")
    previous = set(previous_tickers or [])
    bullets = []
    meta = {}

    if report_type == "model_portfoy":
        tickers = _ticker_candidates(text)
        current = set(tickers)
        meta["tickers"] = tickers
        if current:
            if previous:
                added = sorted(current - previous)
                removed = sorted(previous - current)
                if added:
                    bullets.append("Yeni görünen: " + ", ".join(added[:10]))
                if removed:
                    bullets.append("Listede artık görünmeyen: " + ", ".join(removed[:10]))
            if not bullets:
                bullets.append("Portföyde görülen hisseler: " + ", ".join(tickers[:12]))
        bullets.extend(_key_lines(text, report_type, limit=2))

    elif report_type == "sirket_raporu":
        for label, patterns in COMPANY_PATTERNS.items():
            value = _first_field(text, patterns)
            if not value:
                continue
            if label == "Getiri potansiyeli" and "%" not in value:
                value = f"%{value}"
            bullets.append(f"{label}: {value}")
        bullets.extend(_key_lines(text, report_type, limit=3))

    elif report_type == "teknik_bulten":
        bullets.extend(_key_lines(text, report_type, limit=max_bullets))
        tickers = _ticker_candidates(text)
        if tickers:
            meta["tickers"] = tickers
            if len(bullets) < max_bullets:
                bullets.insert(0, "Öne çıkan hisseler: " + ", ".join(tickers[:10]))

    else:
        bullets.extend(_key_lines(text, report_type, limit=max_bullets))

    # Extractive özet üretilemiyorsa sahte veri yazma.
    bullets = [clean(value) for value in bullets if clean(value)]
    deduped = []
    for value in bullets:
        if value not in deduped:
            deduped.append(value)
    return {"bullets": deduped[:max_bullets], "meta": meta}
