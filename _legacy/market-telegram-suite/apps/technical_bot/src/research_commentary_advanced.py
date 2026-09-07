"""Advanced analyst commentary for the fully integrated research engine.

This layer preserves the existing evidence-bound paragraphs and enriches two
areas where the uploaded reference engines add real analytical value:
company-type valuation-model suitability and MAJOR/SWING/MINOR structure.
"""

from __future__ import annotations

import math
import re
from typing import Any

from src import research_commentary_rich as rich
from src.research_engine import ResearchReport
from src.turkish_text import tr_lower


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _valuation_paragraph(report: ResearchReport) -> str:
    valuation = report.valuation or {}
    score = _finite(valuation.get("score"))
    coverage = _finite(valuation.get("coverage")) or 0.0
    confidence = _finite(valuation.get("model_confidence")) or 0.0
    primary = str(valuation.get("primary_model") or "VERİ YETERSİZ")
    scope = str(valuation.get("scope") or "karşılaştırma evreni yok")
    models = valuation.get("models") or []

    status_groups: dict[str, list[str]] = {}
    for item in models:
        status = str(item.get("status") or "VERİ EKSİK")
        status_groups.setdefault(status, []).append(str(item.get("model") or "—"))

    if score is None:
        relative = (
            "Akran çarpanlarından güvenilir bir göreli değerleme puanı üretilemedi; "
            "bu eksiklik nötr puana çevrilmiyor."
        )
    else:
        relative = (
            f"Göreli çarpan skoru {score:.0f}/100 ve veri kapsamı %{coverage * 100:.0f}; "
            f"karşılaştırma evreni {scope}. Bu puan içsel değer değil, akranlara göre konumu gösteriyor."
        )

    suitable = status_groups.get("UYGUN", []) + status_groups.get("KOŞULLU", [])
    missing = status_groups.get("VERİ EKSİK", [])
    unsuitable = status_groups.get("UYGUN DEĞİL", [])
    model_sentence = f"Şirket tipine göre birincil değerleme yaklaşımı {primary}. "
    if suitable:
        model_sentence += "Çalıştırılabilir/koşullu modeller: " + ", ".join(suitable[:4]) + ". "
    if missing:
        model_sentence += "Girdisi eksik modeller: " + ", ".join(missing[:3]) + ". "
    if unsuitable:
        model_sentence += "Ekonomik olarak uygun görülmeyenler: " + ", ".join(unsuitable[:3]) + ". "

    key_reasons: list[str] = []
    for item in models:
        if item.get("status") in {"VERİ EKSİK", "UYGUN DEĞİL"} and item.get("reason"):
            key_reasons.append(str(item["reason"]))
        if len(key_reasons) >= 2:
            break
    reason_text = " ".join(key_reasons)

    computed = valuation.get("computed_values") or {}
    if computed.get("nav"):
        nav = computed["nav"]
        nav_ps = _finite(nav.get("nav_per_share"))
        relation = computed.get("nav_market_relation") or {}
        pd_nav = _finite(relation.get("pd_nav"))
        value_text = (
            f"Ekspertiz girdileriyle NAD/hisse {nav_ps:.2f}" if nav_ps is not None else "Ekspertiz bazlı NAD hesaplandı"
        )
        if pd_nav is not None:
            value_text += f" ve PD/NAD {pd_nav:.2f}x"
        value_text += "."
    else:
        value_text = (
            "Yeterli model girdisi yoksa sistem hedef fiyat uydurmuyor; özellikle GYO'da gerçek ekspertiz/NAD, "
            "DCF'te şirket-spesifik nakit akımı-WACC-g ve bankada Ke/ROE senaryosu olmadan içsel değer üretmiyor."
        )

    return (
        f"{relative} {model_sentence}Model güveni %{confidence * 100:.0f}. {reason_text} {value_text} "
        "Bu ayrım ucuz görünen bir çarpanın otomatik olarak kaliteli veya yatırım yapılabilir olduğu yanılgısını önlemek için korunuyor."
    )


def _state_text(state: str) -> str:
    return {
        "UP": "yukarı trend",
        "DOWN": "aşağı trend",
        "RANGE": "yatay/range",
        "CONTRACTION": "daralan yapı",
        "EXPANSION": "genişleyen/kararsız yapı",
        "ASCENDING_TRIANGLE": "yükselen üçgen benzeri sıkışma",
        "DESCENDING_TRIANGLE": "alçalan üçgen benzeri sıkışma",
        "INSUFFICIENT": "veri yetersiz",
    }.get(state, tr_lower(state) if state else "veri yetersiz")


def _technical_extension(report: ResearchReport) -> str:
    technical = report.technical or {}
    hierarchy = technical.get("structure_hierarchy") or {}
    if hierarchy.get("summary") in (None, "", "VERİ YETERSİZ"):
        hierarchy_text = "MAJOR/SWING/MINOR yapı hiyerarşisi için yeterli teyitli pivot yok."
    else:
        degree_bits: list[str] = []
        for degree, label in (("MAJOR", "MAJOR"), ("SWING", "SWING"), ("MINOR", "MINOR")):
            item = hierarchy.get(degree) or {}
            state = _state_text(str(item.get("state") or "INSUFFICIENT"))
            confidence = _finite(item.get("confidence"))
            rail = item.get("rail") or {}
            rail_status = str(rail.get("status") or "yok")
            suffix = f", güven %{confidence * 100:.0f}" if confidence is not None else ""
            if rail_status != "yok":
                suffix += f", rail {tr_lower(rail_status)}"
            degree_bits.append(f"{label} {state}{suffix}")
        hierarchy_text = "Yapı dereceleri: " + "; ".join(degree_bits) + "."
        confirmed = int(hierarchy.get("confirmed_rails") or 0)
        hierarchy_text += (
            f" Doğrulanmış yapısal rail sayısı {confirmed}; candidate rail'ler seviye teyidi/confluence olarak sayılmıyor."
        )

    compressions: list[str] = []
    for degree in ("MAJOR", "SWING", "MINOR"):
        compression = (hierarchy.get(degree) or {}).get("compression")
        if compression and compression.get("confirmed"):
            compressions.append(degree)
    compression_text = (
        " " + ", ".join(compressions) + " derecesinde yakınsayan compression rail'i var; kırılım yönü teyit edilmeden trend sayılmıyor."
        if compressions
        else ""
    )

    ma = technical.get("moving_average_regime") or {}
    extension = str(ma.get("extension_risk") or "VERİ YETERSİZ")
    family_parts: list[str] = []
    for key, label in (("short", "5/8/13"), ("medium", "21/34/55"), ("long", "89/144/233")):
        group = ma.get(key) or {}
        family_parts.append(f"{label} {tr_lower(str(group.get('confirmation') or '—'))}")
    ma_text = " Ortalama aileleri: " + ", ".join(family_parts) + f"; kısa EMA uzaklaşma riski {tr_lower(extension)}."

    vp = technical.get("volume_profile") or {}
    poc_values = []
    for key, label in (("short_poc", "kısa"), ("medium_poc", "orta"), ("long_poc", "uzun")):
        value = _finite(vp.get(key))
        if value is not None:
            poc_values.append(f"{label} POC {value:.2f}")
    poc_text = " Hacim-fiyat hafızasında " + ", ".join(poc_values) + "." if poc_values else " Hacim POC ufukları için veri yetersiz."

    participation = technical.get("participation") or {}
    label = tr_lower(str(participation.get("label") or "VERİ YETERSİZ"))
    relative_turnover = _finite(participation.get("relative_turnover"))
    impulse = _finite(participation.get("price_impulse_5d_pct"))
    part_text = f" Katılım okuması {label}"
    if relative_turnover is not None:
        part_text += f"; TL hacim medyanın {relative_turnover:.2f} katı"
    if impulse is not None:
        part_text += f" ve 5 günlük fiyat itkisi %{impulse:+.1f}"
    part_text += "."

    return hierarchy_text + compression_text + ma_text + poc_text + part_text


def compose_research_commentary(report: ResearchReport) -> tuple[tuple[str, str], ...]:
    sections = list(rich.compose_research_commentary(report))
    result: list[tuple[str, str]] = []
    for title, paragraph in sections:
        if title == "DEĞERLEME NASIL?":
            paragraph = _valuation_paragraph(report)
        elif title == "TEKNİK YAPI NE DİYOR?":
            paragraph = paragraph + " " + _technical_extension(report)
        result.append((title, paragraph))
    return tuple(result)


def _split_block(block: str, limit: int) -> list[str]:
    if len(block) <= limit:
        return [block]
    sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", block) if item.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(sentence[index : index + limit] for index in range(0, len(sentence), limit))
            continue
        candidate = sentence if not current else f"{current} {sentence}"
        if len(candidate) <= limit:
            current = candidate
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def commentary_messages(report: ResearchReport, limit: int = 3900) -> tuple[str, ...]:
    blocks = [f"📌 {title}\n{paragraph}" for title, paragraph in compose_research_commentary(report)]
    messages: list[str] = []
    current = f"🧾 {report.symbol} — ANALİST YORUMU"
    for block in blocks:
        for piece in _split_block(block, limit):
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= limit:
                current = candidate
            else:
                if current:
                    messages.append(current)
                current = piece
    if current:
        messages.append(current)
    return tuple(messages)
