"""Kurulum tanıma katmanı.

Bu modül yönü yapı durumundan uzatmak yerine, fiyatın içinde bulunduğu
teknik durumu adlandırır. Üretilen kurulum bir AL/SAT sinyali veya olasılık
puanı değildir; yalnızca mevcut kanıtların hangi klasik teknik duruma
karşılık geldiğini deterministik biçimde etiketler.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def _number(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _fmt(value: Any, digits: int = 2) -> str:
    number = _number(value)
    return "—" if not math.isfinite(number) else f"{number:,.{digits}f}"


def _streak_while(series: pd.Series, predicate) -> int:
    """Seride sondan başlayarak koşulun kesintisiz sağlandığı bar sayısını verir."""
    count = 0
    for value in reversed(series.dropna().tolist()):
        if predicate(float(value)):
            count += 1
        else:
            break
    return count


def duration_context(data: pd.DataFrame, profile: dict[str, Any], structure: dict[str, Any]) -> dict[str, Any]:
    """Analistin ilk sorduğu 'ne kadar zamandır?' sorularını sayısallaştırır."""
    close = data["Close"]
    squeeze_bars = _streak_while(data["BB_WIDTH_RANK"], lambda value: value <= 25) if "BB_WIDTH_RANK" in data else 0
    low_adx_bars = _streak_while(data["ADX"], lambda value: value < 20) if "ADX" in data else 0
    below_ema21_bars = 0
    above_ema21_bars = 0
    if "EMA_21" in data:
        difference = (close - data["EMA_21"]).dropna()
        below_ema21_bars = _streak_while(difference, lambda value: value < 0)
        above_ema21_bars = _streak_while(difference, lambda value: value > 0)
    val = _number(profile.get("val"))
    vah = _number(profile.get("vah"))
    recent = close.tail(20)
    inside_value_area = int(((recent >= val) & (recent <= vah)).sum()) if math.isfinite(val) and math.isfinite(vah) else 0
    range_20 = _number(data["High"].tail(20).max()) - _number(data["Low"].tail(20).min())
    range_60 = _number(data["High"].tail(60).max()) - _number(data["Low"].tail(60).min())
    compression = range_20 / range_60 if range_60 > 0 else math.nan
    bars_since_high = None
    bars_since_low = None
    if structure.get("high_time"):
        stamps = pd.DatetimeIndex(data.index)
        high_stamp = pd.Timestamp(structure["high_time"])
        low_stamp = pd.Timestamp(structure["low_time"])
        if high_stamp.tzinfo is None and stamps.tz is not None:
            high_stamp = high_stamp.tz_localize(stamps.tz)
            low_stamp = low_stamp.tz_localize(stamps.tz)
        elif high_stamp.tzinfo is not None and stamps.tz is None:
            high_stamp = high_stamp.tz_localize(None)
            low_stamp = low_stamp.tz_localize(None)
        bars_since_high = int((stamps > high_stamp).sum())
        bars_since_low = int((stamps > low_stamp).sum())
    parts = []
    if squeeze_bars >= 2:
        parts.append(f"{squeeze_bars} bardır dar bant bölgesinde")
    if low_adx_bars >= 3:
        parts.append(f"{low_adx_bars} bardır ADX 20 altında")
    if below_ema21_bars >= 2:
        parts.append(f"{below_ema21_bars} bardır EMA21 altında")
    elif above_ema21_bars >= 2:
        parts.append(f"{above_ema21_bars} bardır EMA21 üzerinde")
    if inside_value_area >= 12:
        parts.append(f"son 20 barın {inside_value_area}'i Value Area içinde kapandı")
    return {
        "squeeze_bars": squeeze_bars,
        "low_directionality_bars": low_adx_bars,
        "below_ema21_bars": below_ema21_bars,
        "above_ema21_bars": above_ema21_bars,
        "inside_value_area_20": inside_value_area,
        "range_compression_20_60": compression,
        "bars_since_swing_high": bars_since_high,
        "bars_since_swing_low": bars_since_low,
        "summary": "; ".join(parts) if parts else "Belirgin bir süre birikimi yok",
        "method": "Kesintisiz bar sayımı; takvim günü değil işlem barı sayılır.",
    }


def _failed_break(data: pd.DataFrame, level: float, direction: str, lookback: int = 5) -> dict[str, Any] | None:
    """Seviyenin aşılıp kapanışla geri alınmadığı denemeleri tespit eder."""
    if not math.isfinite(level) or len(data) < lookback + 1:
        return None
    window = data.tail(lookback)
    close = _number(data["Close"].iloc[-1])
    if direction == "down":
        pierced = window["Low"] < level
        if bool(pierced.any()) and close > level and not bool((window["Close"] < level).tail(1).iloc[0]):
            age = int(len(window) - 1 - pierced.to_numpy().nonzero()[0][-1])
            return {"direction": "down", "level": level, "age": age}
    else:
        pierced = window["High"] > level
        if bool(pierced.any()) and close < level and not bool((window["Close"] > level).tail(1).iloc[0]):
            age = int(len(window) - 1 - pierced.to_numpy().nonzero()[0][-1])
            return {"direction": "up", "level": level, "age": age}
    return None


def _confluence_near_price(confluence: dict[str, Any], maximum_atr: float = 0.75) -> dict[str, Any] | None:
    for cluster in confluence.get("clusters", []):
        if abs(_number(cluster.get("distance_atr"), 99)) <= maximum_atr:
            return cluster
    return None


def recognize_setup(
    data: pd.DataFrame,
    context: dict[str, Any],
    semantic: dict[str, Any],
    duration: dict[str, Any],
) -> dict[str, Any]:
    """Mevcut teknik durumu adlandırılmış bir kuruluma eşler."""
    regime = str(context.get("regime", {}).get("state", ""))
    structure = context.get("structure", {})
    profile = context.get("profile", {})
    trend = semantic.get("trend_quality", {})
    momentum = semantic.get("momentum_character", {})
    participation = semantic.get("participation", {})
    price_action = semantic.get("price_action", {})
    confluence = semantic.get("level_confluence", {})
    price = _number(data["Close"].iloc[-1])
    adx = _number(context.get("regime", {}).get("adx"))
    squeeze_bars = int(duration.get("squeeze_bars", 0))
    strong_divergences = [item for item in momentum.get("active_divergences", []) if item.get("quality") in {"Güçlü", "Orta"}]
    near_cluster = _confluence_near_price(confluence)
    failed_down = _failed_break(data, _number(profile.get("val")), "down") or _failed_break(data, _number(structure.get("low")), "down")
    failed_up = _failed_break(data, _number(profile.get("vah")), "up") or _failed_break(data, _number(structure.get("high")), "up")
    structure_tone = str(structure.get("tone", "neutral"))
    trend_tone = str(trend.get("tone", "neutral"))
    reasons: list[str] = []

    def build(name: str, bias: str, tone: str, description: str) -> dict[str, Any]:
        return {"name": name, "bias": bias, "tone": tone, "description": description, "reasons": reasons.copy()}

    # 1) Başarısız kırılım — yapının yönüne rağmen seviye reddedilmişse öncelikli okumadır.
    if failed_down and squeeze_bars < 8:
        reasons.append(f"{_fmt(failed_down['level'])} seviyesi {failed_down['age']} bar önce aşağı denendi, kapanışlar geri kazanıldı")
        if strong_divergences:
            reasons.append(f"{len(strong_divergences)} adet kalitesi düşük olmayan pozitif/negatif uyumsuzluk aktif")
        if near_cluster:
            reasons.append(f"fiyat {_fmt(near_cluster['low'])}–{_fmt(near_cluster['high'])} teknik yoğunlaşmasına yakın")
        return build(
            "Destekte reddedilme / başarısız aşağı kırılım",
            "iki yönlü",
            "warning",
            "Aşağı kırılım denemesi kapanışla teyit edilmedi ve seviye geri alındı. Bu, mevcut aşağı yapıya karşı sayılan bir kanıttır; tek başına yukarı dönüş teyidi değildir.",
        )
    if failed_up and squeeze_bars < 8:
        reasons.append(f"{_fmt(failed_up['level'])} seviyesi {failed_up['age']} bar önce yukarı denendi, kapanış tutunamadı")
        if near_cluster:
            reasons.append(f"fiyat {_fmt(near_cluster['low'])}–{_fmt(near_cluster['high'])} teknik yoğunlaşmasına yakın")
        return build(
            "Dirençte reddedilme / başarısız yukarı kırılım",
            "iki yönlü",
            "warning",
            "Yukarı kırılım denemesi kapanışla teyit edilmedi. Mevcut yukarı beklentiye karşı kanıttır; aşağı dönüş teyidi değildir.",
        )

    # 2) Sıkışma / karar bölgesi — yön bilgisi üretmeyen, genişleme bekleyen durum.
    if squeeze_bars >= 3 or ("sıkışma" in regime.casefold() and adx < 20):
        if squeeze_bars:
            reasons.append(f"{squeeze_bars} bardır Bollinger genişliği dar bölgede")
        if adx < 20:
            reasons.append(f"ADX {_fmt(adx)} ile yönlülük eşiğinin altında")
        if _number(duration.get("range_compression_20_60"), 1) < 0.6:
            reasons.append("20 barlık aralık 60 barlık aralığın belirgin biçimde altında")
        return build(
            "Sıkışma / karar bölgesi",
            "iki yönlü",
            "neutral",
            "Fiyat daralan bir aralıkta dengede. Bu durum yön bilgisi taşımaz; kırılımın yönü ancak bant genişlemesi, kapanışla seviye kabulü ve katılım artışı birlikte geldiğinde okunabilir.",
        )

    # 3) Trend devamı — yapı, dizilim ve yönlülük aynı yönde.
    if structure_tone == trend_tone and structure_tone in {"positive", "negative"} and adx >= 20:
        upward = structure_tone == "positive"
        reasons.append(f"yapı {structure.get('state', '—')} ve EMA dizilimi aynı yönde")
        reasons.append(f"ADX {_fmt(adx)} ile yönlülük eşiği üzerinde")
        if str(participation.get("tone")) == structure_tone:
            reasons.append("katılım ana yönü destekliyor")
        return build(
            "Trend devamı",
            "yukarı" if upward else "aşağı",
            structure_tone,
            "Yapı, ortalama dizilimi ve yönlülük ölçüsü aynı yöne işaret ediyor. Devam okuması, karşı yönde yapı kırılımı görülene kadar geçerlidir.",
        )

    # 4) Trend içi geri çekilme — yön korunuyor ama momentum dinleniyor.
    if trend_tone in {"positive", "negative"} and str(momentum.get("tone")) == "warning":
        upward = trend_tone == "positive"
        reasons.append(f"EMA dizilimi {'yukarı' if upward else 'aşağı'} yönde korunuyor")
        reasons.append("momentum karakteri yavaşlama/geçiş gösteriyor")
        if near_cluster:
            reasons.append(f"fiyat {_fmt(near_cluster['low'])}–{_fmt(near_cluster['high'])} referans bölgesinde")
        return build(
            "Trend içi geri çekilme",
            "yukarı" if upward else "aşağı",
            "warning",
            "Ana dizilim korunurken momentum dinleniyor. Geri çekilmenin devam mı yoksa dönüş mü olduğu, referans bölgesindeki kapanış davranışıyla ayrışır.",
        )

    # 5) Tükenme denemesi — uyumsuzluk + seviye + aşırılık bir arada.
    rsi = _number(momentum.get("rsi", {}).get("value"))
    if strong_divergences and near_cluster and (rsi <= 35 or rsi >= 65):
        reasons.append(f"{len(strong_divergences)} aktif uyumsuzluk teyitli pivotlarla oluştu")
        reasons.append(f"fiyat {_fmt(near_cluster['low'])}–{_fmt(near_cluster['high'])} yoğunlaşmasında")
        reasons.append(f"RSI {_fmt(rsi)} ile uç bölgeye yakın")
        return build(
            "Tükenme denemesi",
            "iki yönlü",
            "warning",
            "Uyumsuzluk, teknik yoğunlaşma ve momentum aşırılığı aynı anda mevcut. Bu erken bir uyarıdır; yapı kırılımı veya seviye geri kazanımı olmadan dönüş sayılmaz.",
        )

    # 6) Mücadele bölgesi — hacim var, fiyat ilerlemiyor.
    if participation.get("low_progress_high_volume"):
        reasons.append("ortalama üstü hacme rağmen fiyat ilerlemesi sınırlı")
        if near_cluster:
            reasons.append(f"işlem {_fmt(near_cluster['low'])}–{_fmt(near_cluster['high'])} bölgesinde yoğunlaşıyor")
        return build(
            "Mücadele / emilim bölgesi",
            "iki yönlü",
            "warning",
            "Yüksek katılıma rağmen fiyat mesafe almıyor. OHLCV verisiyle bunun birikim mi dağıtım mı olduğu ayrıştırılamaz; yön, bölgeden kapanışla çıkışta belli olur.",
        )

    # 7) Fallback — sınıflanamayan geçiş.
    reasons.append(f"yapı {structure.get('state', '—')}, dizilim ve momentum tam uyumlu değil")
    if math.isfinite(adx):
        reasons.append(f"ADX {_fmt(adx)}")
    price_state = str(price_action.get("state", ""))
    if price_state:
        reasons.append(f"son bar: {price_state.casefold()}")
    return build(
        "Yön arayışı / geçiş",
        "iki yönlü",
        "warning",
        f"Katmanlar tek bir klasik kuruluma oturmuyor; fiyat {_fmt(price)} çevresinde yön arıyor. Bu durumda tek göstergeye dayalı okuma zayıf kalır.",
    )


REGIME_WEIGHTS = {
    "squeeze": {"Konum": 1.5, "Volatilite": 1.5, "Yapı": 1.2, "Katılım": 0.6, "Momentum": 0.5, "Trend": 0.8, "Göreceli güç": 1.0, "Fiyat davranışı": 1.0},
    "trend": {"Trend": 1.5, "Momentum": 1.2, "Katılım": 1.2, "Yapı": 1.3, "Konum": 0.8, "Volatilite": 0.7, "Göreceli güç": 1.1, "Fiyat davranışı": 0.9},
    "transition": {"Yapı": 1.2, "Konum": 1.2, "Trend": 1.0, "Momentum": 0.9, "Katılım": 1.0, "Volatilite": 1.0, "Göreceli güç": 1.0, "Fiyat davranışı": 1.0},
}


def regime_family(regime: str) -> str:
    lowered = regime.casefold()
    if "sıkışma" in lowered or "denge" in lowered:
        return "squeeze"
    if lowered.startswith(("trend", "yönlü")):
        return "trend"
    return "transition"


def evidence_weight(regime: str, family: str) -> float:
    return REGIME_WEIGHTS[regime_family(regime)].get(family, 1.0)


def participation_reading(
    participation: dict[str, Any],
    regime: str,
    duration: dict[str, Any],
    setup: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Aynı RVOL değerini rejime ve tanınan kuruluma göre farklı okur."""
    rvol = _number(participation.get("rvol_1"))
    base = str(participation.get("state", "—"))
    setup_name = str((setup or {}).get("name", "")).casefold()
    in_squeeze = regime_family(regime) == "squeeze" or "sıkışma" in setup_name or int(duration.get("squeeze_bars", 0)) >= 5
    if in_squeeze and rvol < 1.0:
        squeeze_bars = int(duration.get("squeeze_bars", 0))
        suffix = f" ({squeeze_bars} bardır süren sıkışma)" if squeeze_bars else ""
        return {
            "state": "Sıkışmayla uyumlu düşük katılım",
            "tone": "neutral",
            "rvol_1": rvol,
            "meaning": (
                f"RVOL {rvol:.2f}x sıkışma rejiminde beklenen davranıştır{suffix}; trend içindeki düşük katılım gibi zayıflık kanıtı sayılmaz. "
                "Asıl bilgi, kırılım denemesine hacim eşlik edip etmediğinde ortaya çıkar."
            ),
        }
    if regime_family(regime) == "trend" and rvol < 0.8:
        return {
            "state": base,
            "tone": "warning",
            "rvol_1": rvol,
            "meaning": f"RVOL {rvol:.2f}x trend rejiminde katılım zayıflığına işaret eder; devam hareketleri için teyit eksiktir.",
        }
    return {"state": base, "tone": str(participation.get("tone", "neutral")), "rvol_1": rvol, "meaning": str(participation.get("summary", "—"))}


def reconcile(
    setup: dict[str, Any],
    supporting: list[dict[str, str]],
    counter: list[dict[str, str]],
) -> str:
    """Karşı kanıtı listelemekle yetinmeyip okumaya nasıl dahil edildiğini açıklar."""
    if str(setup.get("bias", "")) == "iki yönlü":
        upward = [item["family"].casefold() for item in supporting if item.get("tone") == "positive"]
        downward = [item["family"].casefold() for item in supporting + counter if item.get("tone") == "negative"]
        if upward or downward:
            return (
                f"Kanıtlar tek yöne toplanmıyor: yukarı tarafta {', '.join(upward) or 'belirgin katman yok'}; "
                f"aşağı tarafta {', '.join(downward) or 'belirgin katman yok'}. "
                f"{setup['name']} sınıflamasının koşullu olmasının nedeni budur; yön, aşağıdaki eşiklerden biri "
                "kapanışla aşıldığında okunabilir hale gelir."
            )
        return (
            f"Katmanların hiçbiri belirgin yön üretmiyor; {setup['name'].casefold()} okuması bu nedenle koşullu tutuluyor."
        )
    if not counter:
        return (
            f"Karşı kanıt saptanmadı; {setup['name'].casefold()} okuması "
            f"{', '.join(item['family'].casefold() for item in supporting[:3]) or 'mevcut katmanlar'} tarafından destekleniyor."
        )
    strongest = counter[0]
    others = [item["family"].casefold() for item in counter[1:3]]
    tail = f" Ayrıca {', '.join(others)} katmanı da tam uyumlu değil." if others else ""
    return (
        f"Bu okuma karşı kanıta rağmen kuruluyor: {strongest['family'].casefold()} katmanı "
        f"'{strongest['state'].casefold()}' diyor.{tail} "
        f"{setup['name']} sınıflaması bu çelişkiyi yok saymaz; kurulumun iki yönlü/koşullu olmasının nedeni budur. "
        "Çelişki ancak aşağıdaki teyit koşullarından biri kapanışla gerçekleşirse çözülür."
    )


def build_setup_context(
    data: pd.DataFrame,
    context: dict[str, Any],
    semantic: dict[str, Any],
) -> dict[str, Any]:
    profile = context.get("profile", {})
    structure = context.get("structure", {})
    regime = str(context.get("regime", {}).get("state", ""))
    duration = duration_context(data, profile, structure)
    setup = recognize_setup(data, context, semantic, duration)
    participation = participation_reading(semantic.get("participation", {}), regime, duration, setup)
    return {
        "setup": setup,
        "duration": duration,
        "participation_reading": participation,
        "regime_family": regime_family(regime),
        "method": "Kurulum etiketi deterministik kural sırasıyla üretilir; olasılık veya başarı puanı içermez.",
    }
