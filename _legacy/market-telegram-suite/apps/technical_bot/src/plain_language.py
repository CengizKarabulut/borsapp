"""Sade dil katmanı.

Teknik rapor uzman için yazılmıştır. Bu modül aynı bulguları teknik terim
kullanmadan, kısa cümlelerle özetler. Amaç basitleştirme değil, erişilebilirlik:
hiçbir yeni iddia üretilmez, yalnızca mevcut sınıflamalar gündelik dile çevrilir.
"""

from __future__ import annotations

import math
from typing import Any

SETUP_PLAIN = {
    "Destekte reddedilme / başarısız aşağı kırılım": (
        "Fiyat aşağı kırmayı denedi ama başaramadı; sarktığı yerden geri döndü."
    ),
    "Dirençte reddedilme / başarısız yukarı kırılım": (
        "Fiyat yukarı çıkmayı denedi ama tutunamadı; yükseldiği yerden geri geldi."
    ),
    "Sıkışma / karar bölgesi": (
        "Fiyat bir süredir dar bir aralıkta gidip geliyor. Henüz yön seçmiş değil."
    ),
    "Trend devamı": (
        "Fiyat belirgin bir yönde ilerliyor ve göstergeler bu yönü destekliyor."
    ),
    "Trend içi geri çekilme": (
        "Ana yön korunuyor ama hareket şu an duraklamış durumda."
    ),
    "Tükenme denemesi": (
        "Mevcut hareket yorulma belirtisi gösteriyor. Bu bir dönüş işareti değil, sadece erken uyarı."
    ),
    "Mücadele / emilim bölgesi": (
        "Alıcı ve satıcı bu seviyede çekişiyor; işlem çok ama fiyat pek yol almıyor."
    ),
    "Yön arayışı / geçiş": (
        "Göstergeler birbirini tutmuyor; fiyat şu an net bir yön göstermiyor."
    ),
}


def _number(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _fmt(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    return "—" if not math.isfinite(number) else f"{number:,.2f}"


def _participation_plain(rvol: float, in_squeeze: bool) -> str:
    if not math.isfinite(rvol):
        return "İşlem yoğunluğu hesaplanamadı."
    if rvol < 0.8:
        if in_squeeze:
            return "İşlem hacmi normalin altında, ama sıkışma dönemlerinde bu beklenen bir durum."
        return "İşlem hacmi normalin altında; yani harekete katılım zayıf."
    if rvol >= 1.5:
        return "İşlem hacmi normalin belirgin şekilde üzerinde; harekete katılım yüksek."
    return "İşlem hacmi normal seviyelerde."


INTERVAL_WORDS = {
    "5m": ("5 dakikalık mum", "mum"),
    "15m": ("15 dakikalık mum", "mum"),
    "30m": ("30 dakikalık mum", "mum"),
    "1h": ("saatlik mum", "mum"),
    "2h": ("2 saatlik mum", "mum"),
    "4h": ("4 saatlik mum", "mum"),
    "1d": ("gün", "gün"),
    "1wk": ("hafta", "hafta"),
    "1mo": ("ay", "ay"),
}


def bar_state_plain(bar_state: dict[str, Any] | None) -> str:
    """CANLI/TEYİTLİ etiketinin, mum aralığına uygun gündelik karşılığı."""
    state = bar_state or {}
    unit, _ = INTERVAL_WORDS.get(str(state.get("interval", "1d")), ("gün", "gün"))
    opened = "Gün sürüyor" if unit == "gün" else f"Bu {unit} henüz kapanmadı"
    closed = "Gün kapandı" if unit == "gün" else f"{unit.capitalize()} kapandı"
    if state.get("is_live"):
        return f"{opened} — rakamlar kapanışa kadar değişebilir"
    if str(state.get("label", "")) == "TEYİTLİ":
        return f"{closed} — rakamlar kesinleşti"
    if state.get("market_state") == "CLOSED":
        return f"Piyasa kapalı — son tamamlanan {unit} rakamları"
    return "Bar durumu bilinmiyor"


def build_plain_summary(
    symbol: str,
    price: float,
    change_pct: float,
    setup_context: dict[str, Any],
    scenario: dict[str, Any],
    clarity: dict[str, Any],
    bar_state: dict[str, Any] | None = None,
    short_history: bool = False,
) -> dict[str, Any]:
    """Raporun ana bulgusunu teknik terim kullanmadan anlatır."""
    setup = setup_context.get("setup", {})
    name = str(setup.get("name", ""))
    bias = str(setup.get("bias", ""))
    duration = setup_context.get("duration", {})
    participation = setup_context.get("participation_reading", {})
    rvol = participation.get("rvol_1")
    if rvol is None:
        rvol = math.nan
    in_squeeze = int(duration.get("squeeze_bars", 0)) >= 3 or "sıkışma" in name.casefold()

    sentences: list[str] = [
        f"{symbol} {_fmt(price)} seviyesinde, günü %{change_pct:+.2f} değişimle kapattı."
    ]
    sentences.append(SETUP_PLAIN.get(name, "Fiyatın durumu klasik bir kalıba tam oturmuyor."))

    squeeze_bars = int(duration.get("squeeze_bars", 0))
    if squeeze_bars >= 3:
        sentences.append(f"Bu dar aralık {squeeze_bars} işlem günüdür sürüyor.")

    plain_participation = _participation_plain(float(rvol), in_squeeze)
    sentences.append(plain_participation)

    def threshold_only(item: str) -> str:
        """Senaryo metninden yalnızca eşik ifadesini alır, teknik etiketi atar."""
        return item.split(":")[0].strip().casefold()

    upward = [item for item in scenario.get("strengthen", []) if "yukarı" in item.casefold()]
    downward = [item for item in scenario.get("strengthen", []) if "aşağı" in item.casefold()]
    if bias == "iki yönlü" and upward and downward:
        sentences.append(
            f"Yön iki eşikten biriyle belli olur: {threshold_only(upward[0])} olursa yukarı, "
            f"{threshold_only(downward[0])} olursa aşağı."
        )
    elif scenario.get("strengthen"):
        sentences.append(f"İzlenecek ilk eşik: {threshold_only(scenario['strengthen'][0])}.")

    clarity_state = str(clarity.get("state", ""))
    if clarity_state == "Düşük":
        sentences.append("Şu an göstergeler birbirini net biçimde doğrulamıyor; bekleyip görmek için sebep var.")
    elif clarity_state == "Orta":
        sentences.append("Bir eğilim var ama henüz kesinleşmiş değil.")
    elif clarity_state == "Yüksek":
        sentences.append("Göstergelerin büyük kısmı aynı şeyi söylüyor.")

    if bar_state and bar_state.get("is_live"):
        sentences.append("Not: mevcut mum henüz kapanmadı, bu rakamlar kapanışa kadar değişebilir.")

    if short_history:
        sentences.append("Not: bu hissenin işlem geçmişi kısa, bu yüzden uzun vadeli ortalamalar hesaplanamadı; okuma daha az veriye dayanıyor.")
    sentences.append("Bu bir alım veya satım tavsiyesi değildir; yalnızca fiyatın mevcut durumunun özetidir.")
    return {
        "text": " ".join(sentences),
        "sentences": sentences,
        "method": "Teknik sınıflamaların gündelik dile birebir çevirisi; yeni bir iddia veya tahmin içermez.",
    }


SCAN_SETUP_PLAIN = {
    "Destekte reddedilme / başarısız aşağı kırılım": "Fiyat aşağı kırmayı denedi ama başaramadı, geri döndü.",
    "Dirençte reddedilme / başarısız yukarı kırılım": "Fiyat yukarı çıkmayı denedi ama tutunamadı, geri geldi.",
    "Sıkışma / karar bölgesi": "Fiyat dar bir aralıkta sıkışmış, henüz yön seçmemiş.",
    "Trend devamı": "Fiyat belirgin bir yönde ilerliyor.",
    "Trend içi geri çekilme": "Ana yön korunuyor ama hareket duraklamış.",
    "Tükenme denemesi": "Mevcut hareket yorulma belirtisi gösteriyor.",
    "Mücadele / emilim bölgesi": "Alıcı ve satıcı çekişiyor, fiyat yol almıyor.",
    "Yön arayışı / geçiş": "Göstergeler birbirini tutmuyor, yön belirsiz.",
}


def _volume_phrase(rvol: float, observed: float = math.nan, fraction: float = 1.0) -> str:
    """Hacim cümlesi; canlı barda gerçekleşen ve projeksiyon ayrılır."""
    if not math.isfinite(rvol):
        return ""
    if fraction < 1.0 and math.isfinite(observed):
        pace = "çok yoğun" if rvol >= 3 else "yoğun" if rvol >= 1.5 else "normal"
        return (
            f"İşlem hacmi şu ana kadar normalin {observed:.1f} katı; bu hızla giderse "
            f"gün sonunda {rvol:.1f} katına ulaşır ({pace} ilgi)."
        )
    if rvol >= 3:
        return f"İşlem hacmi normalin {rvol:.1f} katı — çok yoğun ilgi var."
    if rvol >= 1.5:
        return f"İşlem hacmi normalin {rvol:.1f} katı."
    if rvol < 0.8:
        return "İşlem hacmi normalin altında; ilgi sınırlı."
    return "İşlem hacmi normal seviyelerde."


def _strength_phrase(excess: Any) -> str:
    try:
        value = float(excess)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(value):
        return ""
    if value >= 3:
        return "Son bir ayda endeksten belirgin şekilde iyi performans gösterdi."
    if value <= -3:
        return "Son bir ayda endeksin gerisinde kaldı."
    return "Endeksle benzer performans gösterdi."


def scan_line_plain(item: dict[str, Any]) -> str:
    """Tarama satırını sade anlatır; yalnız doğrulanmış aktif seviyeleri kullanır."""
    parts: list[str] = []
    setup = str(item.get("setup", ""))
    parts.append(SCAN_SETUP_PLAIN.get(setup, "Fiyatın durumu klasik bir kalıba tam oturmuyor."))
    volume = _volume_phrase(
        _number(item.get("rvol")),
        _number(item.get("rvol_observed")),
        _number(item.get("bar_fraction"), 1.0),
    )
    if volume:
        parts.append(volume)
    strength = _strength_phrase(item.get("excess_return_20"))
    if strength:
        parts.append(strength)

    levels = item.get("active_levels") or {}
    lower = _number(levels.get("lower"))
    reference = _number(levels.get("reference_close"))
    upper = _number(levels.get("upper"))
    if all(math.isfinite(value) for value in (lower, reference, upper)) and lower < reference < upper:
        parts.append(
            f"Teyitli referans kapanış {_fmt(reference)}; aktif alt seviye {_fmt(lower)}, "
            f"aktif üst seviye {_fmt(upper)}."
        )
    if len(item.get("matched_intervals", [])) > 1:
        parts.append("Birden fazla zaman diliminde aynı anda öne çıktı.")
    return " ".join(parts)
