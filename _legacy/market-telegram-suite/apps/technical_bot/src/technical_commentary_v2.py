from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from src.plain_language import build_plain_summary
from src.setup_recognition import evidence_weight
from src.state_change import compare_states


def _number(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _fmt(value: Any, digits: int = 2) -> str:
    number = _number(value)
    return "—" if not math.isfinite(number) else f"{number:,.{digits}f}"


def _relation(
    value: Any,
    reference: Any,
    above: str,
    equal: str,
    below: str,
    unavailable: str = "hesaplanamadı",
) -> str:
    """İki değeri NaN ve eşitlik durumlarını bozmadan karşılaştırır."""
    left, right = _number(value), _number(reference)
    if not math.isfinite(left) or not math.isfinite(right):
        return unavailable
    if math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-12):
        return equal
    return above if left > right else below


def _signed(
    value: Any,
    positive: str,
    zero: str,
    negative: str,
    unavailable: str = "hesaplanamadı",
) -> str:
    """İşaret yorumunda sıfırı ve eksik veriyi negatiften ayırır."""
    number = _number(value)
    if not math.isfinite(number):
        return unavailable
    if math.isclose(number, 0.0, rel_tol=0.0, abs_tol=1e-12):
        return zero
    return positive if number > 0 else negative


def _direction(context: dict[str, Any]) -> tuple[str, str]:
    """Yönü yapıdan uzatmak yerine tanınan kurulumun eğiliminden türetir."""
    setup = context.get("setup_context", {}).get("setup", {})
    bias = str(setup.get("bias", ""))
    structure = context.get("structure", {}).get("state", "Yetersiz pivot")
    if bias == "yukarı":
        return f"{setup.get('name', 'Yukarı kurulum')} — yukarı eğilimli", "positive"
    if bias == "aşağı":
        return f"{setup.get('name', 'Aşağı kurulum')} — aşağı eğilimli", "negative"
    if bias == "iki yönlü":
        return f"{setup.get('name', 'Koşullu kurulum')} — koşullu", "warning"
    if structure == "HH / HL":
        return "Yukarı yönlü yapı", "positive"
    if structure == "LH / LL":
        return "Aşağı yönlü yapı", "negative"
    return "Yön teyidi karışık", "warning"


def _regime_opening(regime: str, direction: str, adx: float, adx_delta: float) -> tuple[str, str, str]:
    if "sıkışma" in regime.casefold() or "denge" in regime.casefold():
        return (
            "Denge / teyit bekliyor",
            "warning",
            f"Piyasa {regime.casefold()} rejiminde. Daralan hareket alanında gösterge kesişimlerinin bilgi değeri düşer; yeni yön için bant genişlemesi, kapanışla seviye kabulü ve hacim teyidi gerekir.",
        )
    if "yönsüz" in regime.casefold():
        return (
            "Yönsüz volatilite / seçicilik gerekli",
            "warning",
            f"Volatilite genişliyor fakat yönlülük zayıf; ADX {_fmt(adx)}. Mevcut sınıflama tek başına kalıcı kırılım teyidi değildir.",
        )
    if regime.startswith(("Trend", "Yönlü")):
        strength = "güç kazanıyor" if adx_delta > 0 else "güç kaybediyor" if adx_delta < 0 else "yatay"
        tone = "positive" if direction.startswith(("Yukarı", "Ortalamalar yukarı")) else "negative" if direction.startswith(("Aşağı", "Ortalamalar aşağı")) else "warning"
        return (
            f"{direction} / {regime}",
            tone,
            f"{regime}; ADX {_fmt(adx)} ve bir barlık değişimi {adx_delta:+.2f}, yani yönlülük {strength}.",
        )
    return (
        "Geçiş / çelişkili bağlam",
        "warning",
        f"{regime}. Yapı, momentum ve katılım aynı yönde teyit vermeden tek bir göstergeye dayalı okuma zayıf kalır.",
    )


def _rs_text(decision: dict[str, Any]) -> tuple[str, str, str]:
    rs = decision.get("relative_strength", {})
    if not rs.get("available"):
        return "Benchmark verisi yok", "warning", "Göreceli güç karşılaştırması yapılamadı."
    period = rs.get("periods", {}).get("20", {})
    stock_return = _number(period.get("stock_return_pct"))
    benchmark_return = _number(period.get("benchmark_return_pct"))
    excess = _number(period.get("excess_return_pct"))
    slope = _number(rs.get("ratio_slope_5_pct"))
    meaning = (
        f"Son 20 barda hisse %{stock_return:+.2f}, {rs.get('benchmark', 'benchmark')} %{benchmark_return:+.2f}; "
        f"göreceli fark {excess:+.2f} puan ve rasyo 5 bar eğimi %{slope:+.2f}. "
        "Bu relatif performanstır; doğrudan fon akışı ölçümü değildir."
    )
    return str(rs.get("state", "Göreceli güç karışık")), str(rs.get("tone", "warning")), meaning


def _location_text(context: dict[str, Any]) -> str:
    profile = context.get("profile", {})
    confluence = context.get("semantic", {}).get("level_confluence", {})
    nearest = confluence.get("summary", "Yakın teknik seviye bulunamadı.")
    clusters = confluence.get("clusters", [])
    cluster_text = ""
    if clusters:
        cluster = clusters[0]
        names = ", ".join(cluster["members"][:5])
        cluster_text = f" En yakın yoğunlaşma {_fmt(cluster['low'])}–{_fmt(cluster['high'])} ({names}, {cluster['strength'].casefold()})."
    return (
        f"Fiyat {profile.get('position', 'profil konumu yok')}; {profile.get('developing_acceptance', 'kabul verisi yok')}. "
        f"POC göçü {profile.get('poc_migration', '—')}. {nearest}{cluster_text}"
    )


def _technical_levels(context: dict[str, Any], direction_tone: str) -> dict[str, Any]:
    confluence = context.get("semantic", {}).get("level_confluence", {})
    structure = context.get("structure", {})
    support = confluence.get("nearest_support")
    resistance = confluence.get("nearest_resistance")
    if direction_tone == "positive" and math.isfinite(_number(structure.get("low"))):
        invalidation = f"{_fmt(structure['low'])} altında günlük kapanış mevcut yukarı yapıyı geçersizleştirir."
        invalidation_level = _number(structure["low"])
    elif direction_tone == "negative" and math.isfinite(_number(structure.get("high"))):
        invalidation = f"{_fmt(structure['high'])} üzerinde günlük kapanış mevcut aşağı yapıyı geçersizleştirir."
        invalidation_level = _number(structure["high"])
    else:
        invalidation = "Yapı karışık olduğu için tek bir teknik geçersizlik seviyesi tanımlanmadı."
        invalidation_level = None
    return {
        "nearest_support": support,
        "nearest_resistance": resistance,
        "clusters": confluence.get("clusters", []),
        "invalidation": invalidation,
        "invalidation_level": invalidation_level,
        "method": "Seviyeler izleme referansıdır; emir veya stop önerisi değildir.",
    }


def _changes(data: pd.DataFrame, context: dict[str, Any]) -> list[str]:
    """Okumanın kendisi düne göre nasıl değişti?

    Önceki bar için yeniden hesaplanmış durum varsa alan alan karşılaştırma
    yapılır. Yoksa yalnızca temel gösterge geçişlerine düşülür.
    """
    comparison = compare_states(context.get("previous_state"), context)
    if comparison["available"]:
        context["state_comparison"] = comparison
        return comparison["bullets"]
    row = data.iloc[-1]
    previous = data.iloc[-2]
    changes: list[str] = []
    if previous["RSI"] < 50 <= row["RSI"]:
        changes.append(f"RSI 50 seviyesini geri kazandı ({previous['RSI']:.1f} → {row['RSI']:.1f}).")
    elif previous["RSI"] >= 50 > row["RSI"]:
        changes.append(f"RSI 50 seviyesinin altına indi ({previous['RSI']:.1f} → {row['RSI']:.1f}).")
    if previous["MACD_HIST"] <= 0 < row["MACD_HIST"]:
        changes.append("MACD histogramı negatiften pozitife geçti.")
    elif previous["MACD_HIST"] >= 0 > row["MACD_HIST"]:
        changes.append("MACD histogramı pozitiften negatife geçti.")
    if previous["SMI"] <= previous["SMI_EMA"] and row["SMI"] > row["SMI_EMA"]:
        changes.append("SMI sinyal çizgisini yukarı kesti.")
    elif previous["SMI"] >= previous["SMI_EMA"] and row["SMI"] < row["SMI_EMA"]:
        changes.append("SMI sinyal çizgisini aşağı kesti.")
    for event in context.get("events", []):
        if int(event.get("age", 99)) == 0 and event.get("event") not in " ".join(changes):
            changes.append(f"Yeni olay: {event['event']} ({event['state']}).")
    regime = context.get("regime", {})
    if regime.get("candidate") and regime.get("candidate") != regime.get("state"):
        changes.append(f"Rejim adayı {regime['candidate']}; kalıcı sınıflama için devam teyidi bekleniyor.")
    profile = context.get("profile", {})
    if profile.get("poc_migration") not in (None, "Yatay"):
        changes.append(f"POC {profile['poc_migration'].casefold()} davranışına geçti.")
    return changes[:5] or ["Son barda ana teknik sınıflamayı değiştiren yeni bir olay oluşmadı."]


def _threshold_distance(text: str, price: float) -> float:
    """Senaryo metnindeki seviyenin fiyata uzaklığını bulur; yakın eşikler öne alınır."""
    distances = []
    for token in re.findall(r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?", text):
        cleaned = token.replace(",", "") if token.count(".") == 1 and "," in token else token.replace(",", ".")
        try:
            value = float(cleaned)
        except ValueError:
            continue
        if price * 0.5 <= value <= price * 2.0:
            distances.append(abs(value - price) / price)
    return min(distances) if distances else math.inf


def _scenario_map(
    context: dict[str, Any],
    decision: dict[str, Any],
    direction_tone: str,
    levels: dict[str, Any],
) -> dict[str, list[str]]:
    profile = context.get("profile", {})
    structure = context.get("structure", {})
    semantic = context.get("semantic", {})
    participation = semantic.get("participation", {})
    strengthen: list[str] = []
    weaken: list[str] = []
    neutral: list[str] = []
    setup = context.get("setup_context", {}).get("setup", {})
    bias = str(setup.get("bias", ""))
    if bias == "iki yönlü":
        strengthen.append(f"{_fmt(structure.get('high'))} üzerinde kapanış: yukarı çözülme")
        strengthen.append(f"{_fmt(structure.get('low'))} altında kapanış: aşağı çözülme")
        weaken.append("Her iki uçta da kapanışla kabul oluşmadan aralık içinde kalınması")
    elif direction_tone == "positive":
        strengthen.append(f"{_fmt(structure.get('high'))} swing zirvesi üzerinde kapanış ve retest başarısı")
        weaken.append(levels["invalidation"])
    elif direction_tone == "negative":
        strengthen.append(f"{_fmt(structure.get('low'))} swing dibi altında kapanış ve aşağı kabul")
        weaken.append(levels["invalidation"])
    else:
        strengthen.append("Teyitli yapı kırılımıyla yönün netleşmesi")
        weaken.append("Kırılım denemesinin yeniden denge alanına dönmesi")
    if "içinde" in str(profile.get("position", "")):
        strengthen.append(f"VAH {_fmt(profile.get('vah'))} üzerinde veya VAL {_fmt(profile.get('val'))} altında kapanış + developing kabul")
        neutral.append(f"POC {_fmt(profile.get('poc'))} çevresinde düşük RVOL ile rotasyon")
    elif "üzerinde" in str(profile.get("position", "")):
        strengthen.append(f"VAH {_fmt(profile.get('vah'))} üzerinde kalıcılık ve RVOL artışı")
        weaken.append("Value Area içine geri dönüş")
    else:
        strengthen.append(f"VAL {_fmt(profile.get('val'))} altında kalıcılık ve RVOL artışı")
        weaken.append("Value Area içine geri kazanım")
    strengthen.append("Ana yönle uyumlu MACD histogram genişlemesi ve RVOL ≥ 1,10x")
    if _number(participation.get("rvol_1")) < 0.8:
        neutral.append("RVOL 0,80x altında kaldıkça hareketin katılım teyidinin sınırlı kalması")
    if "sıkışma" in str(context.get("regime", {}).get("state", "")).casefold():
        neutral.append("Bantlar genişlemeden ve kapanışla seviye kabulü oluşmadan sıkışmanın sürmesi")
    if decision.get("multi_timeframe", {}).get("tone") == "warning":
        weaken.append("Zaman dilimi ayrışmasının sürmesi")
    labels = (
        {"strengthen": "Yukarı/aşağı çözülme koşulları", "weaken": "Kurulumu geçersiz kılacak gelişmeler", "neutral": "Durumu koruyacak gelişmeler"}
        if bias == "iki yönlü"
        else {"strengthen": "Mevcut okumayı teyit edecek gelişmeler", "weaken": "Mevcut okumayı zayıflatacak gelişmeler", "neutral": "Durumu nötr tutacak gelişmeler"}
    )
    price = _number(context.get("last_price"))
    if math.isfinite(price):
        strengthen.sort(key=lambda item: _threshold_distance(item, price))
        weaken.sort(key=lambda item: _threshold_distance(item, price))
    return {"strengthen": strengthen[:3], "weaken": weaken[:3], "neutral": neutral[:3], "labels": labels}


def _evidence_and_clarity(
    context: dict[str, Any],
    decision: dict[str, Any],
    direction_tone: str,
    bar_state: dict[str, Any] | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, str]]:
    semantic = context.get("semantic", {})
    families = [
        ("Yapı", context.get("structure", {}).get("state", "—"), context.get("structure", {}).get("tone", "neutral")),
        ("Trend", semantic.get("trend_quality", {}).get("state", "—"), semantic.get("trend_quality", {}).get("tone", "neutral")),
        ("Momentum", semantic.get("momentum_character", {}).get("state", "—"), semantic.get("momentum_character", {}).get("tone", "neutral")),
        ("Katılım", semantic.get("participation", {}).get("state", "—"), semantic.get("participation", {}).get("tone", "neutral")),
        ("Konum", context.get("profile", {}).get("position", "—"), context.get("profile", {}).get("tone", "neutral")),
        ("Göreceli güç", decision.get("relative_strength", {}).get("state", "—"), decision.get("relative_strength", {}).get("tone", "neutral")),
        ("Fiyat davranışı", semantic.get("price_action", {}).get("state", "—"), semantic.get("price_action", {}).get("tone", "neutral")),
    ]
    setup = context.get("setup_context", {}).get("setup", {})
    if setup.get("name"):
        setup_evidence_tone = {"yukarı": "positive", "aşağı": "negative"}.get(str(setup.get("bias")), "")
        if not setup_evidence_tone and "aşağı kırılım" in str(setup["name"]).casefold():
            setup_evidence_tone = "positive"
        elif not setup_evidence_tone and "yukarı kırılım" in str(setup["name"]).casefold():
            setup_evidence_tone = "negative"
        if setup_evidence_tone:
            families.append(("Kurulum", setup["name"], setup_evidence_tone))
    for divergence in semantic.get("momentum_character", {}).get("active_divergences", []):
        if divergence.get("quality") not in {"Güçlü", "Orta"}:
            continue
        label = str(divergence.get("state", ""))
        divergence_tone = "positive" if "pozitif" in label.casefold() else "negative" if "negatif" in label.casefold() else ""
        if divergence_tone:
            families.append((
                f"Uyumsuzluk ({divergence.get('indicator', '—')})",
                f"{label} — {divergence.get('quality', '—')} kalite",
                divergence_tone,
            ))
    supporting: list[dict[str, str]] = []
    counter: list[dict[str, str]] = []
    two_sided = str(context.get("setup_context", {}).get("setup", {}).get("bias", "")) == "iki yönlü"
    for family, state, tone in families:
        item = {"family": family, "state": str(state), "tone": str(tone)}
        if two_sided:
            if tone == "positive":
                supporting.append(item)
            elif tone == "negative":
                counter.append(item)
        elif tone == direction_tone:
            supporting.append(item)
        elif tone in {"positive", "negative"} and direction_tone in {"positive", "negative"}:
            counter.append(item)
    if decision.get("multi_timeframe", {}).get("tone") == "warning":
        counter.append({"family": "MTF", "state": "Günlük/haftalık/aylık yönler tam uyumlu değil", "tone": "warning"})
    if bar_state and bar_state.get("is_live"):
        counter.append({"family": "Bar", "state": "Son mum CANLI; kapanışa kadar sınıflamalar değişebilir", "tone": "warning"})
    regime = str(context.get("regime", {}).get("state", ""))
    supporting_weight = sum(evidence_weight(regime, item["family"]) for item in supporting)
    counter_weight = sum(evidence_weight(regime, item["family"]) for item in counter)
    supporting.sort(key=lambda item: evidence_weight(regime, item["family"]), reverse=True)
    counter.sort(key=lambda item: evidence_weight(regime, item["family"]), reverse=True)
    if two_sided:
        upward_weight, downward_weight = supporting_weight, counter_weight
        total = upward_weight + downward_weight
        weight_note = f"Rejime göre ağırlıklı yukarı kanıt {upward_weight:.1f}, aşağı kanıt {downward_weight:.1f}."
        dominant = max(upward_weight, downward_weight)
        if total == 0:
            clarity = {"state": "Düşük", "tone": "warning", "reason": f"Hiçbir katman belirgin yön üretmiyor. {weight_note}"}
        elif dominant / total >= 0.75:
            side = "yukarı" if upward_weight > downward_weight else "aşağı"
            clarity = {
                "state": "Orta",
                "tone": "neutral",
                "reason": f"Kanıtlar {side} tarafta yoğunlaşıyor fakat kurulum kapanışla teyit beklediği için okuma koşullu kalıyor. {weight_note}",
            }
        else:
            clarity = {"state": "Düşük", "tone": "warning", "reason": f"Kanıtlar iki yöne dağılmış durumda. {weight_note}"}
    else:
        weight_note = f"Rejime göre ağırlıklı kanıt {supporting_weight:.1f}, karşı kanıt {counter_weight:.1f}."
        if counter_weight <= 1.0 and supporting_weight >= 4.0:
            clarity = {"state": "Yüksek", "tone": "positive", "reason": f"Rejimde ağırlığı yüksek aileler aynı yönde. {weight_note}"}
        elif counter_weight >= supporting_weight * 0.8:
            clarity = {"state": "Düşük", "tone": "warning", "reason": f"Rejimde ağırlığı yüksek aileler belirgin biçimde ayrışıyor. {weight_note}"}
        else:
            clarity = {"state": "Orta", "tone": "neutral", "reason": f"Ana okuma mevcut ancak bazı katmanlar teyidi sınırlıyor. {weight_note}"}
    clarity["supporting_weight"] = round(supporting_weight, 2)
    clarity["counter_weight"] = round(counter_weight, 2)
    return supporting[:4], counter[:4], clarity


def _analyst_note(
    opening: str,
    context: dict[str, Any],
    decision: dict[str, Any],
    scenario: dict[str, list[str]],
    reconciliation: str = "",
) -> str:
    semantic = context.get("semantic", {})
    trend = semantic.get("trend_quality", {}).get("summary", "Trend kalitesi hesaplanamadı.")
    momentum = semantic.get("momentum_character", {}).get("summary", "Momentum karakteri hesaplanamadı.")
    price_action = semantic.get("price_action", {}).get("summary", "Fiyat davranışı hesaplanamadı.")
    participation = semantic.get("participation", {}).get("summary", "Katılım hesaplanamadı.")
    _, _, rs = _rs_text(decision)
    location = _location_text(context)
    divergences = semantic.get("momentum_character", {}).get("active_divergences", [])
    divergence_text = ""
    if divergences:
        details = "; ".join(
            f"{item.get('indicator', 'Osilatör')} {item.get('state', 'uyumsuzluk')} ({item.get('quality', '—')} kalite; teyit {item.get('event_age', '—')} bar önce, pivotu 5 bar öncesinde)"
            for item in divergences
        )
        divergence_text = f" Aktif uyumsuzluklar: {details}; bunlar erken kanıttır ve yapı/seviye teyidi gerektirir."
    strengthen_first = scenario["strengthen"][0].rstrip(". ")
    weaken_first = scenario["weaken"][0].rstrip(". ")
    if str(context.get("setup_context", {}).get("setup", {}).get("bias", "")) == "iki yönlü":
        closing = f"Yönü netleştirecek ilk eşik: {strengthen_first}. Kurulumu geçersiz kılacak gelişme: {weaken_first}."
    else:
        closing = f"Mevcut okumayı teyit edecek ilk koşul: {strengthen_first}. Okumayı geçersizleştirecek ilk koşul: {weaken_first}."
    setup_context = context.get("setup_context", {})
    setup = setup_context.get("setup", {})
    duration = setup_context.get("duration", {})
    participation_reading = setup_context.get("participation_reading", {})
    if participation_reading.get("meaning"):
        participation = participation_reading["meaning"]
    setup_paragraph = ""
    if setup:
        reasons = "; ".join(setup.get("reasons", [])[:3])
        setup_paragraph = (
            f"Kurulum: {setup['name']} (eğilim: {setup['bias']}). {setup['description']}"
            + (f" Bu sınıflamanın dayanağı: {reasons}." if reasons else "")
        )
    duration_paragraph = ""
    if duration.get("summary") and duration["summary"] != "Belirgin bir süre birikimi yok":
        duration_paragraph = f"Süre bağlamı: {duration['summary']}."
    paragraphs = [
        f"{opening} {setup_paragraph}".strip(),
        f"{trend} {momentum}{divergence_text}".strip(),
        f"{price_action} {participation} {duration_paragraph}".strip(),
        f"{location} {rs}".strip(),
        closing,
    ]
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def _short_history_note(context: dict[str, Any]) -> str:
    """Hesaplanamayan periyotları adıyla bildirir; ikame yapılmadığını belirtir."""
    missing = ", ".join(str(period) for period in context.get("missing_periods", [])) or "bazı"
    return (
        f"Sembolün geçmişi kısa ({context.get('bar_count', '—')} bar); {missing} periyotluk "
        "ortalamalar hesaplanamadı ve başka periyotlarla ikame edilmedi."
    )


LITERATURE_BASIS = [
    {
        "source": "Wilder (1978), New Concepts in Technical Trading Systems",
        "role": "RSI, ATR, ADX/DMI ve Parabolic SAR farklı soruları ölçer; tek puana indirgenmez.",
    },
    {
        "source": "Brock, Lakonishok & LeBaron (1992), Journal of Finance",
        "role": "Trend ve kırılım kuralları tarihsel örneklerde bilgi taşıyabilir; sonuç piyasa ve döneme bağlıdır.",
    },
    {
        "source": "Blume, Easley & O'Hara (1994), Journal of Finance",
        "role": "Hacim, fiyatın tek başına göstermediği katılım ve bilgi kalitesi bağlamını sağlayabilir.",
    },
    {
        "source": "Lo, Mamaysky & Wang (2000), Journal of Finance",
        "role": "Grafik örüntüleri ölçülebilir hale getirilebilir; yine de istatistiksel ve koşullu okunmalıdır.",
    },
    {
        "source": "Bajgrowicz & Scaillet (2012), Journal of Financial Economics",
        "role": "Veri madenciliği, kural seçimi ve işlem maliyetleri görünen teknik başarıyı ortadan kaldırabilir.",
    },
]


def _side(up: bool, down: bool) -> str:
    if up and not down:
        return "up"
    if down and not up:
        return "down"
    return "mixed"


def _indicator_schemas(data: pd.DataFrame) -> list[dict[str, str]]:
    """Dört kullanıcı şemasını durum, anlam, teyit ve risk cümlelerine çevirir.

    Aynı ailedeki göstergeler oy gibi sayılmaz. Her şemada fiyat/trend ana
    bağlamdır; ivme, volatilite ve hacim o bağlamı teyit eder veya sınırlar.
    """
    row = data.iloc[-1]
    previous = data.iloc[-2]
    price = _number(row.get("Close"))

    bb_mid = _number(row.get("BB_MID"))
    bb_upper = _number(row.get("BB_UPPER"))
    bb_lower = _number(row.get("BB_LOWER"))
    bb_width = _number(row.get("BB_WIDTH"))
    prev_width = _number(previous.get("BB_WIDTH"))
    macd_hist = _number(row.get("MACD_HIST"))
    prev_hist = _number(previous.get("MACD_HIST"))
    smi = _number(row.get("SMI"))
    smi_signal = _number(row.get("SMI_EMA"))
    obv = _number(row.get("OBV"))
    obv_ma = _number(row.get("OBV_SMA"))
    bb_side = _side(price > bb_mid, price < bb_mid)
    impulse_side = _side(macd_hist > 0 and smi > smi_signal, macd_hist < 0 and smi < smi_signal)
    flow_side = _side(obv > obv_ma, obv < obv_ma)
    schema1_side = bb_side if bb_side == impulse_side == flow_side else "mixed"
    schema1_tone = {"up": "positive", "down": "negative"}.get(schema1_side, "warning")
    if not all(math.isfinite(value) for value in (price, bb_mid, bb_upper, bb_lower)):
        band_position = "konumu hesaplanamadı"
    elif price > bb_upper:
        band_position = "üst bandın üzerinde"
    elif price < bb_lower:
        band_position = "alt bandın altında"
    else:
        band_position = _relation(
            price, bb_mid, "orta çizginin üzerinde", "orta çizgiyle aynı seviyede", "orta çizginin altında"
        )
    width_state = _relation(
        bb_width, prev_width, "genişliyor", "değişmiyor", "daralıyor"
    )
    if not math.isfinite(macd_hist) or not math.isfinite(prev_hist):
        macd_state = "durumu hesaplanamadı"
    elif macd_hist >= 0:
        macd_state = "pozitif bölgede ve güçleniyor" if macd_hist > prev_hist else (
            "pozitif ve değişmiyor" if math.isclose(macd_hist, prev_hist) else "pozitif ama ivme kaybediyor"
        )
    else:
        macd_state = "negatif bölgede fakat baskı azalıyor" if macd_hist > prev_hist else (
            "negatif ve değişmiyor" if math.isclose(macd_hist, prev_hist) else "negatif bölgede ve baskı artıyor"
        )
    schema1 = {
        "name": "1 · Bollinger / MACD / SMI / OBV",
        "state": {
            "up": "Fiyat, ivme ve hacim yukarı yönde uyumlu",
            "down": "Fiyat, ivme ve hacim aşağı yönde uyumlu",
        }.get(schema1_side, "Fiyat, ivme ve hacim aynı şeyi söylemiyor"),
        "tone": schema1_tone,
        "guide": (
            "Genel okuma: Bollinger orta çizgisi fiyatın kısa vadeli denge noktasını, bantların "
            "genişleyip daralması oynaklığın artıp azaldığını gösterir. MACD histogramının yönü "
            "ivmedeki değişimi, SMI'nin sinyal çizgisine göre konumu kısa vadeli hızı, OBV'nin "
            "kendi ortalamasına göre konumu ise hacmin fiyat hareketine eşlik edip etmediğini anlatır."
        ),
        "reading": (
            f"Fiyat {_fmt(price)} ile Bollinger {band_position}; bant alanı {width_state}. "
            f"MACD histogramı {_fmt(macd_hist)} ve {macd_state}. "
            f"SMI {_fmt(smi)}, sinyal çizgisi {_fmt(smi_signal)}; "
            f"OBV {_fmt(obv, 0)}, SMA14 {_fmt(obv_ma, 0)}."
        ),
        "stock_comment": (
            f"Bu hissede fiyat Bollinger {band_position}; MACD {macd_state}. "
            f"SMI {_relation(smi, smi_signal, 'sinyal çizgisinin üzerinde', 'sinyal çizgisiyle aynı seviyede', 'sinyal çizgisinin altında')}, "
            f"OBV ise {_relation(obv, obv_ma, 'kendi ortalamasının üzerinde', 'kendi ortalamasıyla aynı seviyede', 'kendi ortalamasının altında')}. "
            + {
                "up": "Fiyat, hız ve hacim aynı yönde olduğu için yukarı hareket daha sağlıklı görünüyor.",
                "down": "Fiyat, hız ve hacim aynı yönde olduğu için satış baskısı teknik olarak teyit ediliyor.",
            }.get(
                schema1_side,
                "Bu parçalar aynı yönü göstermediği için hissede tek başına bu gruba dayanarak yön seçmek erken.",
            )
        ),
        "plain": (
            "Bu grup hareketin yalnız yönüne değil, hareketin hız kazanıp kazanmadığına "
            "ve işlem hacminin fiyatı destekleyip desteklemediğine bakar. "
            + (
                "Üç katman şu an birbirini destekliyor."
                if schema1_side != "mixed"
                else "Katmanlar ayrıştığı için tek başına güvenilir bir yön mesajı yok."
            )
        ),
        "confirmation": (
            "Teyit için fiyatın Bollinger orta çizgisinin aynı tarafında kapanması, "
            "MACD/SMI ivmesinin o yönde sürmesi ve OBV'nin kendi ortalamasınca desteklenmesi gerekir."
        ),
        "risk": (
            "Fiyat ilerlerken OBV geriler veya MACD histogramı ters yönde daralırsa hareketin "
            "katılımı zayıf olabilir; bant dışına kısa süreli taşma tek başına kırılım sayılmaz."
        ),
    }

    span_a = _number(row.get("VISIBLE_SPAN_A"))
    span_b = _number(row.get("VISIBLE_SPAN_B"))
    cloud_top, cloud_bottom = max(span_a, span_b), min(span_a, span_b)
    rsi = _number(row.get("RSI"))
    rsi_ma = _number(row.get("RSI_MA"))
    cci = _number(row.get("CCI"))
    cci_ma = _number(row.get("CCI_MA"))
    atr_pct = _number(row.get("ATR_PCT"))
    cloud_side = _side(price > cloud_top, price < cloud_bottom)
    oscillator_side = _side(rsi > 50 and cci > 0, rsi < 50 and cci < 0)
    schema2_side = cloud_side if cloud_side == oscillator_side else "mixed"
    schema2_tone = {"up": "positive", "down": "negative"}.get(schema2_side, "warning")
    if not all(math.isfinite(value) for value in (price, cloud_top, cloud_bottom)):
        cloud_state = "buluta göre konumu hesaplanamadı"
    elif price > cloud_top:
        cloud_state = "bulutun üzerinde"
    elif price < cloud_bottom:
        cloud_state = "bulutun altında"
    else:
        cloud_state = "bulut sınırında" if math.isclose(price, cloud_top) or math.isclose(price, cloud_bottom) else "bulutun içinde"
    schema2 = {
        "name": "2 · Ichimoku / RSI / CCI / ATR",
        "state": {
            "up": "Ana yön ve momentum yukarı yönde uyumlu",
            "down": "Ana yön ve momentum aşağı yönde uyumlu",
        }.get(schema2_side, "Ana yön ile momentum arasında ayrışma var"),
        "tone": schema2_tone,
        "guide": (
            "Genel okuma: Fiyat bulutun üzerindeyse ana eğilim olumlu, altındaysa olumsuz, "
            "bulutun içindeyse kararsız kabul edilir. RSI'da 50, CCI'da sıfır yön eşiğidir; "
            "30/70 RSI ve -100/+100 CCI seviyeleri aşırılaşmayı gösterir. ATR yalnızca hareketin "
            "beklenen büyüklüğünü anlatır, yukarı veya aşağı yön söylemez."
        ),
        "reading": (
            f"Fiyat {cloud_state}. RSI {_fmt(rsi)} (SMA14 {_fmt(rsi_ma)}), "
            f"CCI {_fmt(cci)} (SMA14 {_fmt(cci_ma)}), ATR% {_fmt(atr_pct)}."
        ),
        "stock_comment": (
            f"Bu hissede fiyat {cloud_state}; RSI {_relation(rsi, 50, '50 üzerinde', 'tam 50 seviyesinde', '50 altında')} ve "
            f"CCI {_signed(cci, 'sıfır üzerinde', 'tam sıfır seviyesinde', 'sıfır altında')}. ATR, bir barlık tipik hareketin "
            f"yaklaşık %{_fmt(atr_pct)} olduğunu gösteriyor. "
            + {
                "up": "Ana eğilim ile itiş gücü birlikte yukarıyı destekliyor.",
                "down": "Ana eğilim ile itiş gücü birlikte aşağı yönlü baskıyı destekliyor.",
            }.get(
                schema2_side,
                "Ana eğilim ile hız göstergeleri uyuşmadığından hissede geçiş veya kararsızlık öne çıkıyor.",
            )
        ),
        "plain": (
            "Ichimoku büyük resmi, RSI ve CCI hareketin itiş gücünü, ATR ise fiyatın ne kadar "
            "oynak olduğunu anlatır. ATR yön söylemez; beklenebilecek dalga boyunu gösterir. "
            + (
                "Yön ile itiş gücü aynı tarafta."
                if schema2_side != "mixed"
                else "Büyük resim ile kısa vadeli güç aynı tarafta olmadığı için acele yorum yapılmamalı."
            )
        ),
        "confirmation": (
            "Teyit için fiyatın bulut dışında kapanışlarını koruması, RSI'ın 50'nin ve CCI'ın "
            "sıfırın aynı tarafında kalması gerekir."
        ),
        "risk": (
            "Fiyat bulut içine dönerse yön avantajı zayıflar. ATR yükselirken seviyeler korunamıyorsa "
            "bu güçten çok belirsizlik ve daha geniş fiyat salınımı anlamına gelebilir."
        ),
    }

    psar = _number(row.get("PSAR"))
    stoch_k = _number(row.get("STOCH_K"))
    stoch_d = _number(row.get("STOCH_D"))
    vwap = _number(row.get("VWAP"))
    adx = _number(row.get("ADX"))
    plus_di = _number(row.get("PLUS_DI"))
    minus_di = _number(row.get("MINUS_DI"))
    base_side = _side(price > psar and price > vwap, price < psar and price < vwap)
    timing_side = _side(stoch_k > stoch_d and plus_di > minus_di, stoch_k < stoch_d and minus_di > plus_di)
    schema3_side = base_side if base_side == timing_side else "mixed"
    strong_trend = adx >= 25
    schema3_tone = {"up": "positive", "down": "negative"}.get(schema3_side, "warning")
    if schema3_side != "mixed" and not strong_trend:
        schema3_tone = "neutral"
    schema3 = {
        "name": "3 · Parabolic SAR / Stoch RSI / Auto AVWAP / ADX-DMI",
        "state": {
            "up": "Yukarı yönlü takip koşulları uyumlu" if strong_trend else "Yukarı eğilim var, yön gücü henüz sınırlı",
            "down": "Aşağı yönlü takip koşulları uyumlu" if strong_trend else "Aşağı eğilim var, yön gücü henüz sınırlı",
        }.get(schema3_side, "Takip yönü ve kısa vadeli zamanlama ayrışıyor"),
        "tone": schema3_tone,
        "guide": (
            "Genel okuma: Fiyat SAR ve AVWAP'ın üzerindeyse takip yönü yukarı, altındaysa aşağı kabul edilir. "
            "Stoch RSI'da 20 altı aşırı satım, 80 üstü aşırı alım bölgesidir; K/D kesişimi yalnız zamanlama "
            "ipucudur. +DI ile -DI yönü, ADX ise bu yönün gücünü gösterir; ADX 20 altında zayıf, "
            "25 üzerinde daha belirgin trend olarak okunur."
        ),
        "reading": (
            f"Fiyat {_fmt(price)}; SAR {_fmt(psar)}, Auto AVWAP {_fmt(vwap)}. "
            f"Stoch RSI K/D {_fmt(stoch_k)}/{_fmt(stoch_d)}; "
            f"ADX {_fmt(adx)}, +DI {_fmt(plus_di)}, -DI {_fmt(minus_di)}."
        ),
        "stock_comment": (
            f"Bu hissede fiyat SAR'ın {_relation(price, psar, 'üzerinde', 'aynı seviyesinde', 'altında', 'konumu hesaplanamadı')} ve Auto AVWAP'ın "
            f"{_relation(price, vwap, 'üzerinde', 'aynı seviyesinde', 'altında', 'konumu hesaplanamadı')}. Stoch RSI K, D çizgisinin "
            f"{_relation(stoch_k, stoch_d, 'üzerinde', 'aynı seviyesinde', 'altında')}; "
            f"{_relation(plus_di, minus_di, '+DI alıcı yönünü öne çıkarıyor', 'DI çizgileri dengede', '-DI satıcı yönünü öne çıkarıyor')}. "
            f"ADX {_fmt(adx)} ile "
            f"{'hesaplanamadı' if not math.isfinite(adx) else 'trend gücü belirgin' if adx >= 25 else 'trend gücü zayıf' if adx < 20 else 'trend gücü oluşma aşamasında'}. "
            + (
                "Yön ve zamanlama uyumlu olsa da ADX güçlenmeden hareket tam teyitli sayılmaz."
                if schema3_side != "mixed" and not strong_trend
                else "Yön, zamanlama ve trend gücü birlikte teyit veriyor."
                if schema3_side != "mixed"
                else "Takip yönü ile kısa vadeli zamanlama ayrıştığı için bu hissede yanlış sinyal riski yüksek."
            )
        ),
        "plain": (
            "SAR ve hacim ağırlıklı ortalama fiyatın hangi tarafında kalındığını, Stoch RSI kısa "
            "vadeli dönüş zamanlamasını, ADX/DMI ise ortada gerçekten güçlü bir yön olup olmadığını anlatır. "
            + (
                "Yön bileşenleri uyumlu ve ADX yönün belirgin olduğunu gösteriyor."
                if schema3_side != "mixed" and strong_trend
                else "Bu nedenle mevcut hareket henüz tam bir trend teyidi sayılmıyor."
            )
        ),
        "confirmation": (
            "Teyit için fiyatın SAR ve Auto AVWAP'ın aynı tarafında kapanması, ilgili DI çizgisinin "
            "üstün kalması ve ADX'in tercihen 25 üzerinde yükselmesi gerekir."
        ),
        "risk": (
            "Stoch RSI aşırı bölgedeyken tek kesişim yanıltıcı olabilir. ADX düşükse SAR sık yön "
            "değiştirir; AVWAP'ın çevresindeki gidip gelmeler trend yerine dengeye işaret edebilir."
        ),
    }

    supertrend = _number(row.get("SUPERTREND"))
    fisher = _number(row.get("FISHER"))
    fisher_trigger = _number(row.get("FISHER_TRIGGER"))
    cmf = _number(row.get("CMF"))
    momentum = _number(row.get("MOMENTUM"))
    trend_side = _side(price > supertrend, price < supertrend)
    internal_side = _side(fisher > fisher_trigger and cmf > 0 and momentum > 0, fisher < fisher_trigger and cmf < 0 and momentum < 0)
    schema4_side = trend_side if trend_side == internal_side else "mixed"
    schema4_tone = {"up": "positive", "down": "negative"}.get(schema4_side, "warning")
    schema4 = {
        "name": "4 · Supertrend / Fisher / CMF / Momentum",
        "state": {
            "up": "Trend, dönüş ölçümü ve para akışı yukarı yönde uyumlu",
            "down": "Trend, dönüş ölçümü ve para akışı aşağı yönde uyumlu",
        }.get(schema4_side, "Trend ile dönüş/para akışı teyitleri ayrışıyor"),
        "tone": schema4_tone,
        "guide": (
            "Genel okuma: Fiyat Supertrend'in üzerindeyse ana takip yönü yukarı, altındaysa aşağıdır. "
            "Fisher'ın tetik çizgisini kesmesi dönüş hızına ilişkin erken uyarıdır. CMF'nin sıfır üzerinde "
            "olması alım, altında olması satış baskısını; Momentum'un sıfıra göre konumu ise fiyatın "
            "10 bar öncesine göre ilerleyip gerilediğini gösterir."
        ),
        "reading": (
            f"Fiyat {_fmt(price)}, Supertrend {_fmt(supertrend)}. Fisher/Trigger "
            f"{_fmt(fisher)}/{_fmt(fisher_trigger)}, CMF {_fmt(cmf)}, Momentum10 {_fmt(momentum)}."
        ),
        "stock_comment": (
            f"Bu hissede fiyat Supertrend'in {_relation(price, supertrend, 'üzerinde', 'aynı seviyesinde', 'altında', 'konumu hesaplanamadı')}; Fisher "
            f"tetik çizgisinin {_relation(fisher, fisher_trigger, 'üzerinde', 'aynı seviyesinde', 'altında')}, CMF "
            f"{_signed(cmf, 'pozitif', 'nötr (sıfır)', 'negatif')} ve Momentum10 "
            f"{_signed(momentum, 'sıfır üzerinde', 'tam sıfır seviyesinde', 'sıfır altında')}. "
            + {
                "up": "Ana trend, dönüş hızı ve para akışı birlikte yukarı hareketi destekliyor.",
                "down": "Ana trend, dönüş hızı ve para akışı birlikte aşağı yönlü baskıyı destekliyor.",
            }.get(
                schema4_side,
                "Ana yön ile para akışı/hız aynı şeyi söylemediğinden bu hissede hareketin devamı güvenilir biçimde teyit edilmiş değil.",
            )
        ),
        "plain": (
            "Supertrend izlenen ana yönü, Fisher olası dönüş hızını, CMF para giriş-çıkış dengesini, "
            "Momentum ise fiyatın 10 bar öncesine göre ilerleyip ilerlemediğini gösterir. "
            + (
                "Dört bileşen aynı yönü destekliyor."
                if schema4_side != "mixed"
                else "Ana yön ile iç güç aynı şeyi söylemediği için hareketin devamı henüz net değil."
            )
        ),
        "confirmation": (
            "Teyit için fiyatın Supertrend'in aynı tarafında kalması, Fisher'ın tetik çizgisiyle, "
            "CMF'nin sıfır çizgisiyle ve Momentum'un yönüyle uyumunu koruması gerekir."
        ),
        "risk": (
            "Fisher hızlı dönebilir ve tek başına erken sinyal üretebilir. CMF veya Momentum ana "
            "trendi desteklemiyorsa fiyat hareketi katılımsız ya da yorulmaya açık olabilir."
        ),
    }
    return [schema1, schema2, schema3, schema4]


def _indicator_confirmation(data: pd.DataFrame) -> dict[str, Any]:
    """Dört şemanın açıklamasını korur; ayrı oy veya birleşik puan üretmez."""
    schemas = _indicator_schemas(data)
    summary = " ".join(
        f"{item['name'].split(' · ', 1)[0]}. grup: {item['state']}." for item in schemas
    )
    return {
        "state": "Dört gösterge grubu koşullu olarak birlikte okunur",
        "summary": summary,
        "schemas": schemas,
        "method": (
            "Her grupta fiyat/trend ana bağlamdır; ivme, volatilite ve hacim teyit veya risk "
            "olarak kullanılır. Gruplar AL/SAT oyu gibi toplanmaz."
        ),
    }



def _market_story(context: dict[str, Any], schemas: list[dict[str, str]]) -> str:
    """Teknik katmanları jargon kullanmadan kısa bir piyasa hikâyesine çevirir."""
    regime = str(context.get("regime", {}).get("state", "")).casefold()
    semantic = context.get("semantic", {})
    trend_tone = str(semantic.get("trend_quality", {}).get("tone", "neutral"))
    momentum_tone = str(semantic.get("momentum_character", {}).get("tone", "neutral"))
    participation = semantic.get("participation", {})
    participation_tone = str(participation.get("tone", "neutral"))
    positive = sum(item.get("tone") == "positive" for item in schemas)
    negative = sum(item.get("tone") == "negative" for item in schemas)

    if "sıkışma" in regime or "denge" in regime:
        opening = "Hikâye şöyle: Fiyat bir karar alanında sıkışmış; piyasa yeni yönünü henüz seçmiş değil."
    elif positive > negative:
        opening = "Hikâye şöyle: Alıcılar önde, ancak hareketin kalıcı olup olmadığını teyit edecek işaretler hâlâ izlenmeli."
    elif negative > positive:
        opening = "Hikâye şöyle: Satıcı baskısı daha belirgin, ancak bunun yeni bir düşüş dalgasına dönüşüp dönüşmediği henüz kesin değil."
    else:
        opening = "Hikâye şöyle: Alıcılarla satıcılar arasında net üstünlük yok; göstergeler farklı yönlere bakıyor."

    trend_text = {
        "positive": "Ana fiyat yönü alıcıları destekliyor.",
        "negative": "Ana fiyat yönü satıcıları destekliyor.",
        "warning": "Ana fiyat yönü karışık.",
        "neutral": "Ana fiyat yönü belirgin değil.",
    }.get(trend_tone, "Ana fiyat yönü belirgin değil.")
    momentum_text = {
        "positive": "Kısa vadeli hız yukarı tarafta.",
        "negative": "Kısa vadeli hız aşağı tarafta.",
        "warning": "Kısa vadeli hız yön konusunda kararsız.",
        "neutral": "Kısa vadeli hız nötr.",
    }.get(momentum_tone, "Kısa vadeli hız nötr.")
    rvol = _number(participation.get("rvol_1"))
    if participation_tone == "positive":
        volume_text = "İşlem hacmi bu hareketi destekliyor."
    elif math.isfinite(rvol) and rvol < 0.8:
        volume_text = "İşlem hacmi zayıf; görülen hareketin arkasında güçlü bir katılım yok."
    else:
        volume_text = "İşlem hacmi henüz yönü doğrulayacak kadar belirgin değil."
    return f"{opening} {trend_text} {momentum_text} {volume_text}"


def _divergence_plain(context: dict[str, Any]) -> str:
    items = context.get("semantic", {}).get("momentum_character", {}).get("active_divergences", [])
    if not items:
        return ""
    readable = "; ".join(
        f"{item.get('indicator', 'gösterge')} {item.get('state', 'uyumsuzluk')!s} "
        f"({item.get('quality', '—')} kalite)"
        for item in items[:2]
    )
    return (
        f"Ek erken uyarı: {readable}. Bu işaret tek başına dönüş kanıtı değildir; "
        "fiyatın önemli seviyeyi geçmesi ve hacmin eşlik etmesi gerekir."
    )


def _general_interpretation(context: dict[str, Any], scenario: dict[str, list[str]], clarity: dict[str, Any]) -> str:
    """Raporun sonunda kullanılacak, açık ve koşullu genel sonucu üretir."""
    setup = context.get("setup_context", {}).get("setup", {})
    bias = str(setup.get("bias", ""))
    structure = context.get("structure", {})
    high, low = _number(structure.get("high")), _number(structure.get("low"))
    if bias == "iki yönlü" and math.isfinite(high) and math.isfinite(low):
        result = (
            f"Net sonuç: {_fmt(high)} üzerinde kapanış gelirse yukarı hareket ciddiye alınır; "
            f"{_fmt(low)} altında kapanış gelirse satış baskısı güçlenmiş sayılır. "
            "Fiyat bu iki seviye arasında kaldığı sürece en dürüst yorum, kararın henüz verilmediğidir."
        )
    elif bias == "yukarı":
        condition = scenario.get("strengthen", ["fiyatın yakın direnci aşması"])[0].rstrip(". ")
        risk = scenario.get("weaken", ["yakın desteğin kaybedilmesi"])[0].rstrip(". ")
        result = f"Net sonuç: Görünüm yukarı eğilimli. Bunu güçlendirecek ilk gelişme {condition.casefold()}; bu yorumu bozacak ilk gelişme {risk.casefold()}."
    elif bias == "aşağı":
        condition = scenario.get("strengthen", ["fiyatın yakın desteği kaybetmesi"])[0].rstrip(". ")
        risk = scenario.get("weaken", ["yakın direncin aşılması"])[0].rstrip(". ")
        result = f"Net sonuç: Görünüm aşağı eğilimli. Bunu güçlendirecek ilk gelişme {condition.casefold()}; bu yorumu bozacak ilk gelişme {risk.casefold()}."
    else:
        result = "Net sonuç: Şu anda güçlü ve tek yönlü bir teknik sonuç yok; yeni bir kapanış teyidi beklemek gerekiyor."
    return f"{result} Okumanın güven düzeyi {str(clarity.get('state', 'düşük')).casefold()}."


def _plain_consensus(schemas: list[dict[str, str]]) -> str:
    positive = sum(item.get("tone") == "positive" for item in schemas)
    negative = sum(item.get("tone") == "negative" for item in schemas)
    if positive > negative:
        return "Gösterge grupları birlikte okunduğunda alıcı tarafı biraz daha ağır basıyor; yine de bütün gruplar aynı yönde değil."
    if negative > positive:
        return "Gösterge grupları birlikte okunduğunda satıcı tarafı biraz daha ağır basıyor; yine de bütün gruplar aynı yönde değil."
    return "Gösterge grupları birlikte okunduğunda belirgin bir üstünlük yok; sonuç karışık ve teyit bekliyor."


def _evidence_phrase(item: dict[str, Any]) -> str:
    family = str(item.get("family", "teknik gösterge"))
    lowered = family.casefold()
    if "uyumsuzluk" in lowered:
        match = re.search(r"\(([^)]+)\)", family)
        indicator = match.group(1).upper() if match else "Momentum göstergesi"
        return f"{indicator} fiyat düşerken toparlanma ihtimaline işaret ediyor"
    if "göreceli" in lowered:
        return "hisse, karşılaştırılan endeksten daha zayıf ilerliyor"
    if "mtf" in lowered or "zaman" in lowered:
        return "günlük, haftalık ve aylık görünüm aynı yönde değil"
    if "katılım" in lowered or "hacim" in lowered:
        return "işlem hacmi fiyat hareketini yeterince desteklemiyor"
    if "yapı" in lowered:
        return "son tepe ve dipler aşağı yönlü bir fiyat yapısı gösteriyor"
    return f"{family}: {item.get('state', 'karışık')}"


def _plain_reconciliation(setup: dict[str, Any], supporting: list[dict[str, Any]], counter: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    if supporting:
        parts.append("Kurulumu destekleyen işaretler: " + "; ".join(_evidence_phrase(item) for item in supporting))
    if counter:
        parts.append("Karşı taraftaki riskler: " + "; ".join(_evidence_phrase(item) for item in counter))
    setup_name = str(setup.get("name", "mevcut görünüm"))
    parts.append(
        f"Bu nedenle {setup_name} için tek bir yöne güvenmek henüz erken. "
        "Yön ancak belirtilen fiyat eşiği kapanışla geçildiğinde ve işlem hacmi bunu desteklediğinde daha güvenilir hale gelir."
    )
    return ". ".join(part.rstrip(".") for part in parts) + "."


def build_technical_commentary(
    data: pd.DataFrame,
    context: dict[str, Any],
    decision: dict[str, Any],
    bar_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic = context.get("semantic", {})
    direction, direction_tone = _direction(context)
    regime = str(context.get("regime", {}).get("state", "Bilinmeyen rejim"))
    adx = _number(context.get("regime", {}).get("adx"))
    adx_delta = _number(context.get("regime", {}).get("adx_delta"), 0.0)
    stance, tone, opening = _regime_opening(regime, direction, adx, adx_delta)
    levels = _technical_levels(context, direction_tone)
    scenario = _scenario_map(context, decision, direction_tone, levels)
    supporting, counter, clarity = _evidence_and_clarity(context, decision, direction_tone, bar_state)
    changes = _changes(data, context)
    indicator_confirmation = _indicator_confirmation(data)
    indicator_schemas = indicator_confirmation["schemas"]
    schema_rows = [
        [
            item["name"],
            item["state"],
            "Durum · anlam · teyit · risk",
            " ".join([item["reading"], item["plain"], item["confirmation"], item["risk"]]),
            item["tone"],
        ]
        for item in indicator_schemas
    ]
    setup_for_reconciliation = context.get("setup_context", {}).get("setup", {"name": direction})
    reconciliation = _plain_reconciliation(setup_for_reconciliation, supporting, counter)
    market_story = _market_story(context, indicator_schemas)
    candle_story = str(context.get("candlestick_summary", {}).get("story", "Son iki mum için formasyon özeti üretilemedi."))
    divergence_story = _divergence_plain(context)
    general_interpretation = _general_interpretation(context, scenario, clarity)
    analyst_note = divergence_story or (
        "Erken uyarı niteliğinde belirgin bir uyumsuzluk görülmedi. "
        "Ana karar, kapanış seviyeleri ve hacim teyidiyle verilir."
    )
    literature_note = (
        "Araştırmalar teknik örüntülerin bazı dönemlerde bilgi taşıyabildiğini, ancak sonucun "
        "piyasa rejimine, örnekleme, işlem maliyetlerine ve kural seçimine duyarlı olduğunu gösterir. "
        "Bu nedenle rapor tahmin veya mekanik AL/SAT puanı değil; kapanış, bağımsız teyit ve "
        "geçersizlik koşulları üretir."
    )
    rs_state, rs_tone, rs_meaning = _rs_text(decision)
    setup_context = context.get("setup_context", {})
    setup = setup_context.get("setup", {})
    state_map = [
        ["Kurulum", setup.get("name", "—"), f"Eğilim: {setup.get('bias', '—')}", f"{setup.get('description', '—')} {setup_context.get('duration', {}).get('summary', '')}".strip(), setup.get("tone", "warning")],
        ["Rejim", regime, f"ADX Δ {adx_delta:+.2f}", opening, context.get("regime", {}).get("tone", "warning")],
        ["Yapı / trend", f"{context.get('structure', {}).get('state', '—')} | {semantic.get('trend_quality', {}).get('state', '—')}", semantic.get("trend_quality", {}).get("spread_state", "—"), semantic.get("trend_quality", {}).get("summary", "—"), context.get("structure", {}).get("tone", "neutral")],
        ["Momentum", semantic.get("momentum_character", {}).get("state", "—"), semantic.get("momentum_character", {}).get("macd", {}).get("histogram_character", "—"), semantic.get("momentum_character", {}).get("summary", "—"), semantic.get("momentum_character", {}).get("tone", "warning")],
        *schema_rows,
        ["Katılım", setup_context.get("participation_reading", {}).get("state", semantic.get("participation", {}).get("state", "—")), f"RVOL {semantic.get('participation', {}).get('rvol_1', math.nan):.2f}x", setup_context.get("participation_reading", {}).get("meaning", semantic.get("participation", {}).get("summary", "—")), setup_context.get("participation_reading", {}).get("tone", "warning")],
        ["Konum", context.get("profile", {}).get("position", "—"), context.get("profile", {}).get("poc_migration", "—"), _location_text(context), context.get("profile", {}).get("tone", "neutral")],
        ["Göreceli güç", rs_state, f"Eğim5 %{_number(decision.get('relative_strength', {}).get('ratio_slope_5_pct')):+.2f}", rs_meaning, rs_tone],
        ["Fiyat davranışı", semantic.get("price_action", {}).get("state", "—"), ", ".join(semantic.get("price_action", {}).get("patterns", [])) or "Yeni formasyon yok", semantic.get("price_action", {}).get("summary", "—"), semantic.get("price_action", {}).get("tone", "neutral")],
    ]
    plain = build_plain_summary(
        str(context.get("symbol", "—")),
        _number(data["Close"].iloc[-1]),
        _number(context.get("change_pct"), 0.0),
        setup_context,
        scenario,
        clarity,
        bar_state,
        bool(context.get("short_history")),
    )
    original_plain_sentences = list(plain.get("sentences", []))
    disclaimer = original_plain_sentences[-1] if original_plain_sentences else "Bu bir teknik durum yorumudur; yatırım tavsiyesi değildir."
    history_notes = [item for item in original_plain_sentences if "işlem geçmişi kısa" in item.casefold()]
    plain["sentences"] = [
        market_story,
        _plain_consensus(indicator_schemas),
        candle_story,
        *history_notes,
        disclaimer,
    ]
    plain["text"] = " ".join(item for item in plain["sentences"] if item)
    schema_telegram_lines: list[str] = []
    for item in indicator_schemas:
        confirmation = re.sub(r"^Teyit için\s*", "", item["confirmation"], flags=re.IGNORECASE)
        schema_telegram_lines.extend(
            [
                item["name"],
                f"Nasıl okunur? {item['guide']}",
                f"Bu hisse özelinde: {item['stock_comment']}",
                f"Gösterge değerleri: {item['reading']}",
                f"Yönün doğrulanması için: {confirmation}",
                f"Dikkat edilmesi gereken: {item['risk']}",
                "",
            ]
        )
    headline = f"{stance}. {opening} Teknik okuma netliği: {clarity['state'].casefold()}."
    telegram_detail = "\n".join(
        [
            "🗣️ Sade Özet",
            plain["text"],
            "",
            "📐 Dört Gösterge Şeması",
            *schema_telegram_lines,
            "📚 Yöntem ve Literatür Notu",
            literature_note,
            "",
            "⚖️ Neden bu okuma?",
            reconciliation,
            "",
            "🔄 Dünden Bugüne",
            *[f"• {item}" for item in changes],
            "",
            f"✅ {scenario['labels']['strengthen']}",
            *[f"• {item}" for item in scenario["strengthen"]],
            "",
            f"⚠️ {scenario['labels']['weaken']}",
            *[f"• {item}" for item in scenario["weaken"]],
            "",
            f"↔️ {scenario['labels']['neutral']}",
            *[f"• {item}" for item in scenario["neutral"]],
            "",
            f"Okuma netliği: {clarity['state']} — {clarity['reason']}",
            "",
            "🧾 Genel Yorum",
            general_interpretation,
            "",
            "Teknik durum yorumudur; yatırım tavsiyesi veya otomatik AL/SAT sinyali değildir.",
        ]
    )
    return {
        "version": "2.4",
        "setup": setup,
        "duration": setup_context.get("duration", {}),
        "reconciliation": reconciliation,
        "plain_summary": plain,
        "stance": stance,
        "tone": tone,
        "headline": headline,
        "analyst_note": analyst_note,
        "market_story": market_story,
        "candle_story": candle_story,
        "general_interpretation": general_interpretation,
        "indicator_confirmation": indicator_confirmation,
        "indicator_schemas": indicator_schemas,
        "literature_basis": LITERATURE_BASIS,
        "literature_note": literature_note,
        "direction": direction,
        "regime": regime,
        "changes": changes,
        "state_comparison": context.get("state_comparison", {}),
        "supporting_evidence": supporting,
        "counter_evidence": counter,
        "evidence": [f"{item['family']}: {item['state']}" for item in supporting],
        "conflicts": [f"{item['family']}: {item['state']}" for item in counter],
        "clarity": clarity,
        "levels": levels,
        "scenario_map": scenario,
        "state_map": state_map,
        "visual_rows": [[item[0], item[1], item[3], item[4]] for item in state_map],
        "watch": scenario["strengthen"] + scenario["weaken"],
        "telegram_summary": headline,
        "telegram_detail": telegram_detail,
        "framework": ["Regime", "Direction", "Location", "Setup", "Trigger", "Confirmation", "Risk", "Exit"],
        "method": (
            "Deterministik, rejim-duyarlı teknik yorum; dört kullanıcı şemasını bağımsız kanıt "
            "aileleri olarak okur, kapanış/teyit/geçersizlik koşulları verir ve birleşik AL/SAT puanı üretmez."
        ),
        "limitations": [
            *(
                [
                    "VERİ UYARISI: " + str(context.get("corporate_action", {}).get("reason", ""))
                    + " Bu seride göstergeler güvenilir değildir."
                ]
                if context.get("corporate_action", {}).get("suspect")
                else []
            ),
            *(
                [_short_history_note(context)]
                if context.get("short_history")
                else []
            ),
            "Yorum yalnız OHLCV ve türetilmiş teknik bağlama dayanır; haber/KAP/temel veri içermez.",
            "Volume Profile ve delta alanları yaklaşık OHLCV proxy'dir; gerçek footprint değildir.",
            "Göreceli güç fon akışı değildir; RVOL kurumsal katılımı kanıtlamaz.",
            "CANLI mum kapanışa kadar değişebilir; Stoch RSI uyumsuzluk taramasına dahil değildir, diğer uyumsuzluklar ve swingler sağ pivot barları tamamlanınca teyit edilir.",
            "Teknik kuralların geçmiş başarısı geleceğe taşınmayabilir; veri madenciliği ve işlem maliyetleri sonucu zayıflatabilir.",
        ],
    }
