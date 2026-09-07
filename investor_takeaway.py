"""Araştırma raporu özetlerine kanıta dayalı, kontrollü "yatırımcı için anlamı" katmanı ekler.

Bu modül yatırım tavsiyesi üretmez ve PDF'de olmayan fiyat/hedef/koşul uydurmaz.
Önce research_summary içindeki extractive özet çalışır; ardından yalnız raporda bulunan
öneri, getiri potansiyeli, destek/direnç, kırılım/stop ve portföy değişimlerinden kısa
bir anlam çıkarılır.
"""

import re

from research_summary import summarize_report_text as extractive_summary


NUMBER = r"\d{1,6}(?:[.,]\d{1,2})?"
TICKER = r"[A-Z]{3,6}"

POSITIVE_RECOMMENDATIONS = {
    "AL", "BUY", "ENDEKS ÜZERİ", "ENDEKS UZERI", "OUTPERFORM",
}
NEUTRAL_RECOMMENDATIONS = {
    "TUT", "HOLD", "ENDEKSE PARALEL", "MARKET PERFORM",
}
NEGATIVE_RECOMMENDATIONS = {
    "SAT", "SELL", "ENDEKS ALTI", "ENDEKS ALTI", "UNDERPERFORM",
}

TOPIC_ALIASES = (
    (("bist 100", "bist100", "xu100"), "BIST 100"),
    (("faiz", "politika faizi"), "faiz"),
    (("enflasyon", "tüfe", "tufe"), "enflasyon"),
    (("dolar", "usdtry", "kur"), "kur"),
    (("yabancı", "yabanci"), "yabancı yatırımcı"),
    (("viop", "vadeli"), "VİOP"),
    (("bilanço", "bilanco"), "bilanço"),
    (("petrol", "altın", "altin", "emtia"), "emtia"),
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _lines(text):
    result = []
    seen = set()
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = clean(raw).strip("•·-| ")
        if len(line) < 8 or len(line) > 420:
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(line)
    return result


def _field(summary, label):
    prefix = label.lower() + ":"
    for bullet in summary.get("bullets") or []:
        value = clean(bullet)
        if value.lower().startswith(prefix):
            return clean(value.split(":", 1)[1])
    return ""


def _recommendation_tone(value):
    normalized = clean(value).upper()
    if normalized in POSITIVE_RECOMMENDATIONS:
        return "olumlu"
    if normalized in NEUTRAL_RECOMMENDATIONS:
        return "nötr"
    if normalized in NEGATIVE_RECOMMENDATIONS:
        return "temkinli/negatif"
    return ""


def _company_takeaways(summary):
    recommendation = _field(summary, "Öneri")
    target = _field(summary, "Hedef fiyat")
    upside = _field(summary, "Getiri potansiyeli")
    tone = _recommendation_tone(recommendation)

    if not any((recommendation, target, upside)):
        return []

    parts = []
    if recommendation:
        if tone:
            parts.append(f"Kurumun rapordaki görüşü {tone} ({recommendation})")
        else:
            parts.append(f"Kurum görüşü {recommendation}")
    if target:
        parts.append(f"hedef fiyat {target} TL")
    if upside:
        parts.append(f"getiri potansiyeli {upside}")

    sentence = "; ".join(parts).strip()
    return [sentence + "."] if sentence else []


def _model_takeaways(summary):
    added = _field(summary, "Yeni görünen")
    removed = _field(summary, "Listede artık görünmeyen")
    if added and removed:
        return [f"Model portföyde değişim var: {added} yeni görünürken {removed} artık listede değil."]
    if added:
        return [f"Model portföyde yeni görünen hisseler: {added}."]
    if removed:
        return [f"Önceki model portföyde olup bu raporda artık görünmeyen hisseler: {removed}."]
    return []


def _technical_takeaways(text, max_items=2):
    takeaways = []
    for line in _lines(text):
        upper = line.upper()
        ticker_match = re.search(rf"\b({TICKER})\b", upper)
        ticker = ticker_match.group(1) if ticker_match else ""
        label = ticker or ("BIST 100" if re.search(r"BIST\s*100|BIST100|XU100", upper) else "")

        support = re.search(rf"({NUMBER})\s*(?:TL\s*)?destek", line, flags=re.IGNORECASE)
        resistance = re.search(rf"({NUMBER})\s*(?:TL\s*)?diren[çc]", line, flags=re.IGNORECASE)
        if support and resistance:
            subject = f"{label} için" if label else "Raporda"
            takeaways.append(
                f"{subject} {support.group(1)} destek ile {resistance.group(1)} direnç ana izleme bandı olarak öne çıkıyor."
            )

        breakout = re.search(
            rf"({NUMBER})\s*(?:TL\s*)?(?:üzeri|uzeri|üstü|ustu).*?(?:kırılım|kirilim|kapanış|kapanis|momentum|güçlen|guclen)",
            line,
            flags=re.IGNORECASE,
        )
        if breakout:
            subject = f"{label} için " if label else ""
            takeaways.append(
                f"Rapor {subject}{breakout.group(1)} üzerini güçlenme/kırılım teyidi açısından izliyor."
            )

        stop_match = re.search(
            rf"({NUMBER})\s*(?:TL\s*)?(?:destek\s+seviyesi\s+)?(?:altında|altinda|altı|alti).*?(?:stop|zarar\s*kes)",
            line,
            flags=re.IGNORECASE,
        )
        if not stop_match:
            stop_match = re.search(
                rf"({NUMBER})\s*(?:TL\s*)?.{{0,35}}(?:stop[- ]?loss|stop|zarar\s*kes)",
                line,
                flags=re.IGNORECASE,
            )
        if stop_match:
            subject = f"{label} için " if label else ""
            takeaways.append(f"{subject}{stop_match.group(1)} seviyesi raporda stop/risk eşiği olarak belirtiliyor.")

        if len(takeaways) >= max_items:
            break

    return _dedupe(takeaways)[:max_items]


def _macro_takeaways(text, report_type):
    takeaways = _technical_takeaways(text, max_items=1)
    lowered = clean(text).lower()
    topics = []
    for aliases, label in TOPIC_ALIASES:
        if any(alias in lowered for alias in aliases) and label not in topics:
            topics.append(label)
    if len(topics) >= 2:
        takeaways.append("Raporun ana takip başlıkları: " + ", ".join(topics[:5]) + ".")
    elif topics and report_type == "strateji_raporu":
        takeaways.append("Strateji raporunda ana takip başlığı: " + topics[0] + ".")
    return _dedupe(takeaways)[:2]


def _dedupe(values):
    result = []
    seen = set()
    for value in values:
        cleaned = clean(value)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def build_investor_takeaways(text, report_type, summary):
    """Yalnız rapordaki somut kanıttan 0-2 kısa anlam cümlesi üretir."""
    if not clean(text):
        return []
    if report_type == "sirket_raporu":
        return _company_takeaways(summary)[:2]
    if report_type == "model_portfoy":
        return _model_takeaways(summary)[:2]
    if report_type == "teknik_bulten":
        return _technical_takeaways(text, max_items=2)
    if report_type in {"gunluk_bulten", "strateji_raporu"}:
        return _macro_takeaways(text, report_type)
    return []


def summarize_report_text(text, report_type, previous_tickers=None, max_bullets=5):
    """Mevcut extractive özeti korur ve ayrıca `takeaways` alanı ekler."""
    summary = extractive_summary(
        text,
        report_type,
        previous_tickers=previous_tickers,
        max_bullets=max_bullets,
    )
    summary["takeaways"] = build_investor_takeaways(text, report_type, summary)
    return summary
