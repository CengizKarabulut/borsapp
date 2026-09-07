"""Zaman aralığı kayıt defteri.

Her mum aralığı için sağlayıcıdan hangi ham aralığın çekileceğini, ne kadar
geçmiş isteneceğini ve gerekiyorsa hangi kurala göre yeniden örnekleneceğini
tanımlar. 2 saat ve 4 saat hiçbir sağlayıcıda yerel değildir; 1 saatlik
veriden türetilir.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class IntervalSpec:
    """Bir mum aralığının veri ve görüntüleme tanımı."""

    key: str
    label: str
    source_interval: str
    resample_rule: str | None
    default_period: str
    warmup_period: str
    minutes: float
    intraday: bool


INTERVALS: dict[str, IntervalSpec] = {
    "5m": IntervalSpec("5m", "5 dakika", "5m", None, "1mo", "1mo", 5, True),
    "15m": IntervalSpec("15m", "15 dakika", "15m", None, "3mo", "3mo", 15, True),
    "30m": IntervalSpec("30m", "30 dakika", "30m", None, "6mo", "6mo", 30, True),
    "1h": IntervalSpec("1h", "1 saat", "1h", None, "1y", "1y", 60, True),
    "2h": IntervalSpec("2h", "2 saat", "1h", "2h", "2y", "2y", 120, True),
    "4h": IntervalSpec("4h", "4 saat", "1h", "4h", "2y", "2y", 240, True),
    "1d": IntervalSpec("1d", "1 gün", "1d", None, "2y", "2y", 1440, False),
    "1wk": IntervalSpec("1wk", "1 hafta", "1d", "W-MON", "10y", "10y", 10080, False),
    "1mo": IntervalSpec("1mo", "1 ay", "1d", "MS", "max", "max", 43200, False),
}

RESAMPLE_AGGREGATION = {
    "Open": "first",
    "High": "max",
    "Low": "min",
    "Close": "last",
    "Volume": "sum",
}


def resolve(interval: str) -> IntervalSpec:
    """Kullanıcı girdisini bilinen bir aralığa eşler."""
    key = interval.strip().lower()
    aliases = {"60m": "1h", "1wk": "1wk", "1w": "1wk", "w": "1wk", "1month": "1mo", "1M": "1mo", "d": "1d", "1day": "1d"}
    key = aliases.get(key, key)
    if key not in INTERVALS:
        raise ValueError(f"Desteklenmeyen mum aralığı: {interval}. Geçerli değerler: {', '.join(INTERVALS)}")
    return INTERVALS[key]


def _session_chunks(data: pd.DataFrame, bars_per_group: int, columns: dict[str, str]) -> pd.DataFrame:
    """Gün içi barları seans içindeki konumlarına göre gruplar.

    Takvim saatine hizalama, seans sonundaki kapanış barını ayrı bir kutuya
    düşürüp tek barlık sahte mum üretir. Borsalar (ve TradingView) barları
    seans başından itibaren sayar; burada da aynı yöntem kullanılır.
    Gün sonunda artan barlar, sahte kısa mum oluşmasın diye son gruba eklenir.
    """
    frames = []
    for _, day in data.groupby(pd.DatetimeIndex(data.index).date, sort=True):
        count = len(day)
        if not count:
            continue
        full_groups = count // bars_per_group
        remainder = count % bars_per_group
        last_group = max(full_groups - 1, 0)
        # Artan barlar (ör. 18:00 kapanış seansı) tek barlık sahte mum üretmesin
        # diye günün son tam grubuna eklenir.
        groups = [
            last_group if (remainder and full_groups and index >= full_groups * bars_per_group) else min(index // bars_per_group, last_group)
            for index in range(count)
        ]
        aggregated = day.groupby(groups).agg(columns)
        aggregated.index = [day.index[group * bars_per_group] for group in aggregated.index]
        frames.append(aggregated)
    if not frames:
        return data.iloc[:0]
    result = pd.concat(frames)
    result.index = pd.DatetimeIndex(result.index)
    return result.sort_index()


def resample(data: pd.DataFrame, spec: IntervalSpec) -> pd.DataFrame:
    """Ham barları hedef aralığa toplar; eksik dönemleri düşürür."""
    if not spec.resample_rule:
        return data
    columns = {name: rule for name, rule in RESAMPLE_AGGREGATION.items() if name in data.columns}
    if spec.intraday:
        source = INTERVALS.get(spec.source_interval)
        bars_per_group = max(int(spec.minutes // source.minutes), 1) if source else 1
        resampled = _session_chunks(data, bars_per_group, columns)
    else:
        resampled = data.resample(spec.resample_rule, label="left", closed="left", origin="start_day").agg(columns)
    resampled = resampled.dropna(subset=["Open", "High", "Low", "Close"])
    resampled.attrs.update(data.attrs)
    resampled.attrs["resampled_from"] = spec.source_interval
    resampled.attrs["bars_per_group"] = spec.minutes
    return resampled


def usable_ma_periods(bar_count: int, periods: list[int], minimum: int = 6) -> list[int]:
    """Mevcut bar sayısına sığan hareketli ortalama periyotlarını seçer.

    Aylık gibi uzun aralıklarda 377 periyotluk ortalama için yeterli geçmiş
    bulunmaz; rapor hata vermek yerine hesaplanabilen periyotlarla çalışır.
    """
    usable = [period for period in periods if period + 5 <= bar_count]
    return usable if len(usable) >= minimum else periods[:minimum]



def key_ema_periods(available: list[int], preferred: tuple[int, ...] = (21, 55, 233)) -> tuple[int, ...]:
    """Öne çıkarılan Fibonacci üçlüsünden hesaplanabilenleri döndürür.

    Eksik periyot başka bir periyotla ikame edilmez; hesaplanamayan ortalama
    raporda açıkça eksik gösterilir. Sessiz ikame, okuyanın EMA233 sandığı
    çizginin aslında EMA100 olmasına yol açardı.
    """
    return tuple(period for period in preferred if period in available)


def missing_ma_periods(bar_count: int, periods: list[int]) -> list[int]:
    """Veri yetersizliği nedeniyle hesaplanamayan periyotları listeler."""
    return [period for period in periods if period + 5 > bar_count]


# Hacim profili (100 bar), uyumsuzluk taraması (60 bar) ve yapı pivotları için
# gereken mutlak alt sınır. Yeni halka arzlarda uzun ortalamalar hesaplanamaz
# ama rapor yine de üretilebilir.
ABSOLUTE_MINIMUM_BARS = 120


def minimum_bars(spec: IntervalSpec, periods: list[int]) -> int:
    """Bu aralık için kabul edilebilir en düşük bar sayısı.

    Uzun ortalamalar mevcut bar sayısına göre uyarlandığı için 377 periyot
    zorunlu değildir; kısa geçmişli hisseler raporsuz kalmamalıdır.
    """
    return min(max(periods) + 5, ABSOLUTE_MINIMUM_BARS)


def bar_word(spec: IntervalSpec) -> str:
    """Sade dil metinlerinde kullanılacak zaman birimi."""
    return {"1d": "işlem günü", "1wk": "hafta", "1mo": "ay"}.get(spec.key, f"{spec.label} mumu")


def describe(spec: IntervalSpec) -> dict[str, Any]:
    return {
        "key": spec.key,
        "label": spec.label,
        "source_interval": spec.source_interval,
        "resampled": bool(spec.resample_rule),
        "intraday": spec.intraday,
        "minutes": spec.minutes,
    }

# Yüzdelik hesaplarında kullanılacak geriye bakış penceresi (bar sayısı).
# Amaç her aralıkta benzer bir takvim süresine karşılık gelmesidir; sabit 252
# bar günlükte bir yıl, 5 dakikalıkta ise yalnızca üç güne denk gelir.
RANK_WINDOWS = {
    "5m": 1900,   # ~3 ay
    "15m": 1300,  # ~6 ay
    "30m": 800,   # ~7 ay
    "1h": 500,    # ~9 ay
    "2h": 300,    # ~1 yıl
    "4h": 250,    # ~1 yıl
    "1d": 252,    # 1 yıl
    "1wk": 104,   # 2 yıl
    "1mo": 60,    # 5 yıl
}


def rank_window(interval: str) -> int:
    """Yüzdelik sıralamalarının bu aralıktaki geriye bakış penceresi."""
    return RANK_WINDOWS.get(resolve(interval).key, 252)
