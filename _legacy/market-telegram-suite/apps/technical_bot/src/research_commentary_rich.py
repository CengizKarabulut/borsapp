"""Interpretive analyst commentary contract for /analiz and /rapor.

The commentary does not merely enumerate indicators. It explains alignment,
contradiction, missing confirmation, level roles and what would change the current
reading. All conclusions remain deterministic and evidence-bound.
"""

from __future__ import annotations

import re

from src import research_commentary as base
from src.research_engine import ResearchReport
from src.turkish_text import tr_lower


def _zone(value: float | None, *, upper: float, lower: float, high: str, low: str) -> str:
    if value is None:
        return "veri yetersiz"
    if value >= upper:
        return high
    if value <= lower:
        return low
    return "nötr bölge"


def _direction(value: float | None, signal: float | None) -> str:
    if value is None or signal is None:
        return "sinyal karşılaştırması için veri yetersiz"
    if value > signal:
        return "sinyal çizgisinin üzerinde"
    if value < signal:
        return "sinyal çizgisinin altında"
    return "sinyal çizgisiyle aynı seviyede"


def _upper(value: object) -> str:
    return str(value or "").upper()


def _structure_bias(state: object, event: object) -> int:
    text = f"{_upper(state)} {_upper(event)}"
    bearish = any(token in text for token in ("LL", "LH", "AŞAĞI", "DÜŞ"))
    bullish = any(token in text for token in ("HH", "HL", "YUKARI", "YÜKSEL"))
    if bearish and not bullish:
        return -1
    if bullish and not bearish:
        return 1
    return 0


def _technical_paragraph_rich(report: ResearchReport) -> str:
    technical = report.technical
    structure = technical.get("structure", {})
    weekly = technical.get("weekly_structure", {})
    monthly = technical.get("monthly_structure", {})
    elliott = technical.get("elliott", {})

    score = base._finite(technical.get("score"))
    score_text = "—" if score is None else f"{score:.0f}/100"
    label = tr_lower(str(technical.get("label", "VERİ YETERSİZ")))

    daily_state = structure.get("state", "—")
    daily_event = structure.get("event", structure.get("bos", "—"))
    weekly_state = weekly.get("state", "—")
    weekly_event = weekly.get("event", "—")
    monthly_state = monthly.get("state", "—")
    monthly_event = monthly.get("event", "—")

    biases = [
        _structure_bias(daily_state, daily_event),
        _structure_bias(weekly_state, weekly_event),
        _structure_bias(monthly_state, monthly_event),
    ]
    known_biases = [value for value in biases if value != 0]
    if known_biases and all(value < 0 for value in known_biases):
        structure_read = "Okunabilen zaman dilimleri aynı yönde aşağı eğilim gösteriyor; bu, kısa vadeli zayıflığın üst zaman dilimiyle de çelişmediği anlamına geliyor."
    elif known_biases and all(value > 0 for value in known_biases):
        structure_read = "Okunabilen zaman dilimleri aynı yönde yukarı eğilim gösteriyor; teknik yapı çoklu zaman diliminde uyumlu."
    elif len(known_biases) >= 2:
        structure_read = "Zaman dilimleri aynı yönde değil; bu nedenle tek bir günlük kırılımı ana trend değişimi olarak okumak için üst zaman dilimi teyidi gerekiyor."
    else:
        structure_read = "Çoklu zaman dilimi teyidi sınırlı; mevcut yapı yorumu ağırlıklı olarak günlük veriye dayanıyor."

    rsi = base._finite(technical.get("rsi14"))
    smi = base._finite(technical.get("smi"))
    smi_signal = base._finite(technical.get("smi_signal"))
    macd_hist = base._finite(technical.get("macd_hist"))
    obv_change = base._finite(technical.get("obv_10d_change"))
    rvol = base._finite(technical.get("rvol20"))
    atr_pct = base._finite(technical.get("atr_pct"))
    divergence = technical.get("latest_rsi_divergence")
    divergence_text = divergence.get("kind") if isinstance(divergence, dict) else "yok"

    rsi_zone = _zone(rsi, upper=70.0, lower=30.0, high="aşırı alım", low="aşırı satım")
    smi_zone = _zone(smi, upper=40.0, lower=-40.0, high="+40 üzeri aşırı alım", low="-40 altı aşırı satım")

    alpha = _upper(technical.get("alpha_trend_state", "—"))
    bollinger = _upper(technical.get("bollinger_state", "—"))
    alpha_bearish = "ALTINDA" in alpha or "DÜŞ" in alpha
    alpha_bullish = "ÜSTÜNDE" in alpha or "YÜKSEL" in alpha
    bollinger_extreme_low = "ALT BAND ALTI" in bollinger
    bollinger_extreme_high = "ÜST BAND ÜSTÜ" in bollinger

    momentum_parts: list[str] = []
    oversold = (rsi is not None and rsi <= 30) or (smi is not None and smi <= -40)
    overbought = (rsi is not None and rsi >= 70) or (smi is not None and smi >= 40)
    macd_bearish = macd_hist is not None and macd_hist < 0
    macd_bullish = macd_hist is not None and macd_hist > 0
    has_divergence = str(divergence_text).casefold() not in ("", "yok", "none", "—")

    if oversold and macd_bearish and not has_divergence:
        momentum_parts.append(
            "RSI/SMI aşırı satım tarafına inmiş olsa da MACD negatif ve doğrulanmış regular pozitif uyumsuzluk yok; bu nedenle mevcut durum 'dönüş başladı' değil, satışın aşırılaşmış olabileceği fakat teyidin henüz gelmediği bir bölge."
        )
    elif oversold and (macd_bullish or has_divergence):
        momentum_parts.append(
            "Aşırı satım bölgesine momentum iyileşmesi eşlik ediyor; bu tepki ihtimalini artırıyor ancak piyasa yapısı değişmeden ana trend dönüşü teyit edilmiş sayılmaz."
        )
    elif overbought and macd_bullish:
        momentum_parts.append("Momentum güçlü fakat aşırı alım bölgesinde; trend devamı mümkün olsa da yeni girişte risk-getiri marjı daralabilir.")
    elif overbought and macd_bearish:
        momentum_parts.append("Aşırı alım bölgesinde MACD zayıflaması momentum kaybına işaret ediyor; fiyat yapısındaki ilk bozulma daha önemli hale geliyor.")
    else:
        momentum_parts.append("Momentum göstergeleri aşırı bir bölgeyi tek başına teyit etmiyor; yön için piyasa yapısı ve seviye davranışı daha belirleyici.")

    if alpha_bearish:
        momentum_parts.append("AlphaTrend fiyatın altında/düşen konumdaysa trend filtresi de zayıflığı destekliyor.")
    elif alpha_bullish:
        momentum_parts.append("AlphaTrend yukarı yönlü konumdaysa trend filtresi fiyat yapısına destek veriyor.")
    if bollinger_extreme_low:
        momentum_parts.append("Fiyatın alt Bollinger bandının altında olması istatistiksel olarak genişlemiş bir satış hareketine işaret eder; bu tek başına dip teyidi değildir.")
    elif bollinger_extreme_high:
        momentum_parts.append("Fiyatın üst Bollinger bandının üzerinde olması güçlü ivme gösterebilir ancak kısa vadeli taşma riskini de artırır.")

    if obv_change is None:
        obv_text = "OBV yönü için yeterli veri yok"
    elif obv_change > 0:
        obv_text = "OBV son 10 günlük ölçümde yukarı yönlü; hacim akışı fiyatı destekliyor"
    elif obv_change < 0:
        obv_text = "OBV son 10 günlük ölçümde aşağı yönlü; hacim akışı fiyat hareketini desteklemekten çok zayıflatıyor"
    else:
        obv_text = "OBV son 10 günlük ölçümde yatay"

    if rvol is None:
        volume_text = "RVOL20 için veri yetersiz"
    elif rvol >= 1.5:
        volume_text = f"RVOL20 {rvol:.2f}x; hareket olağanın üzerinde katılımla gerçekleşiyor"
    elif rvol >= 0.8:
        volume_text = f"RVOL20 {rvol:.2f}x; hacim normal aralıkta"
    else:
        volume_text = f"RVOL20 {rvol:.2f}x; hacim zayıf, dolayısıyla olası tepkinin güvenilirliği düşük"

    if atr_pct is None:
        volatility_text = "ATR için veri yetersiz"
    elif atr_pct >= 7:
        volatility_text = f"ATR %{atr_pct:.1f}; volatilite çok yüksek ve seviye etrafındaki normal fiyat salınımı geniş"
    elif atr_pct >= 5:
        volatility_text = f"ATR %{atr_pct:.1f}; volatilite yüksek"
    elif atr_pct >= 2.5:
        volatility_text = f"ATR %{atr_pct:.1f}; volatilite orta"
    else:
        volatility_text = f"ATR %{atr_pct:.1f}; volatilite görece düşük"

    invalidation = base._finite(elliott.get("invalidation"))
    confidence = base._finite(elliott.get("confidence"))
    invalidation_text = "—" if invalidation is None else f"{invalidation:,.2f}"
    confidence_text = "—" if confidence is None else f"%{confidence:.0f}"
    elliott_primary = str(elliott.get("primary", "—"))
    elliott_alt = str(elliott.get("alternate", "—"))
    elliott_upper = _upper(elliott_primary)
    if "DÜŞ" in elliott_upper and oversold:
        elliott_read = "Elliott ana sayımı düşüş itkisini korurken aşırı satım göstergeleri bir düzeltme/tepki alanı oluşabileceğini söylüyor; tepki ile trend dönüşü birbirinden ayrılmalı."
    elif "YÜK" in elliott_upper and overbought:
        elliott_read = "Elliott ana sayımı yukarı yönü destekliyor ancak momentumun aşırı alımda olması dalga olgunluğu açısından izlenmeli."
    else:
        elliott_read = "Elliott sayımı ana yapıya bağlam sağlıyor; tek başına seviye veya yön teyidi yerine alternatif senaryoyla birlikte okunmalı."

    divergence_read = (
        f"Son doğrulanmış RSI uyumsuzluğu: {divergence_text}."
        if has_divergence
        else "Doğrulanmış RSI uyumsuzluğu yok."
    )

    if score is not None and score < 30:
        verdict = "Teknik puan çok düşük; karşı-trend tepki olasılığı olsa bile ana teknik tez şu aşamada savunmacı kalmalı."
    elif score is not None and score >= 70:
        verdict = "Teknik puan güçlü; yine de devam senaryosunun geçerliliği aktif destek/direnç yaşam döngüsüyle sınanmalı."
    else:
        verdict = "Teknik puan tek başına yön kararı vermiyor; teyit ve geçersizleşme seviyeleri belirleyici."

    alpha_text = tr_lower(alpha) if alpha not in ("", "—") else "veri yetersiz"
    bollinger_text = tr_lower(bollinger) if bollinger not in ("", "—") else "veri yetersiz"

    return (
        f"Teknik yapı {score_text} ile {label}. Günlük: {daily_state} / {daily_event}; haftalık: {weekly_state} / "
        f"{weekly_event}; aylık: {monthly_state} / {monthly_event}. {structure_read} "
        f"Trend filtrelerinde AlphaTrend {alpha_text}; Bollinger konumu {bollinger_text}. "
        f"RSI {base._num(rsi)} ({rsi_zone}), SMI {base._num(smi)} ({smi_zone}, {_direction(smi, smi_signal)}), "
        f"MACD {'pozitif' if macd_bullish else 'negatif' if macd_bearish else 'nötr/veri yetersiz'} histogram. "
        f"{divergence_read} "
        f"{' '.join(momentum_parts)} Hacim tarafında {volume_text}; {obv_text}. {volatility_text}. "
        f"Elliott ana senaryo {elliott_primary}, alternatif {elliott_alt}, güven {confidence_text}, invalidation "
        f"{invalidation_text}. {elliott_read} {verdict}"
    )


def compose_research_commentary(report: ResearchReport) -> tuple[tuple[str, str], ...]:
    """Return the analyst sections in the user-facing order."""
    return (
        ("ŞİRKET NE DURUMDA?", base._company_paragraph(report)),
        ("DEĞERLEME NASIL?", base._valuation_paragraph(report)),
        ("BİLANÇO İYİLEŞİYOR MU?", base._balance_paragraph(report)),
        ("KÂR KALİTELİ Mİ?", base._earnings_paragraph(report)),
        ("BORÇ VE NAKİT NE YÖNDE?", base._debt_paragraph(report)),
        ("TEKNİK YAPI NE DİYOR?", _technical_paragraph_rich(report)),
        ("KRİTİK SEVİYELER NEREDE?", base._levels_paragraph(report)),
        ("ASIL RİSK NE?", base._risk_paragraph(report)),
        ("SONUÇ", base._conclusion_paragraph(report)),
    )


def _split_long_block(block: str, limit: int) -> list[str]:
    """Bir bölüm tek başına limiti aşarsa cümle sınırından böl."""
    if len(block) <= limit:
        return [block]
    parts: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?…])\s+", block):
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(sentence) > limit:
            parts.append(sentence[:limit])
            sentence = sentence[limit:]
        current = sentence
    if current:
        parts.append(current)
    return parts


def commentary_messages(report: ResearchReport, limit: int = 3900) -> tuple[str, ...]:
    """Split the ordered paragraphs at section boundaries, never above ``limit``."""
    blocks: list[str] = []
    for title, paragraph in compose_research_commentary(report):
        blocks.extend(_split_long_block(f"📌 {title}\n{paragraph}", limit))
    messages: list[str] = []
    current = f"🧾 {report.symbol} — ANALİST YORUMU"
    for block in blocks:
        candidate = f"{current}\n\n{block}"
        if len(candidate) <= limit:
            current = candidate
            continue
        messages.append(current)
        current = block
    if current:
        messages.append(current)
    return tuple(messages)
