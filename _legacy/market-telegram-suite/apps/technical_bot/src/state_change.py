"""Dünden bugüne durum karşılaştırması.

Önceki raporun çıktısını saklamak yerine, son bar atılarak aynı hesap yeniden
çalıştırılır ve iki durum alan alan karşılaştırılır. Böylece hiçbir geçmiş
dosyaya bağımlılık olmaz ve karşılaştırma her zaman aynı kodla yapılır.

Bu bölüm gösterge kesişimlerini değil, okumanın kendisinin nasıl değiştiğini
anlatır; "Son 12 Teyitli Olay" tablosuyla çakışmaz.
"""

from __future__ import annotations

import math
from typing import Any

BULLETS_LIMIT = 6


def _number(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _fmt(value: Any, digits: int = 2) -> str:
    number = _number(value)
    return "—" if not math.isfinite(number) else f"{number:,.{digits}f}"


def _get(context: dict[str, Any], *path: str, default: Any = None) -> Any:
    current: Any = context
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def _setup_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = str(_get(previous, "setup_context", "setup", "name", default="—"))
    after = str(_get(current, "setup_context", "setup", "name", default="—"))
    if before == after or "—" in (before, after):
        return []
    return [{
        "field": "Kurulum",
        "text": f"Kurulum değişti: {before} → {after}.",
        "tone": str(_get(current, "setup_context", "setup", "tone", default="warning")),
    }]


def _bias_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = str(_get(previous, "setup_context", "setup", "bias", default="—"))
    after = str(_get(current, "setup_context", "setup", "bias", default="—"))
    if before == after or "—" in (before, after):
        return []
    return [{"field": "Eğilim", "text": f"Kurulum eğilimi {before} → {after} oldu.", "tone": "warning"}]


def _structure_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = str(_get(previous, "structure", "state", default="—"))
    after = str(_get(current, "structure", "state", default="—"))
    if before == after:
        return []
    return [{"field": "Yapı", "text": f"Dış yapı {before} → {after} olarak değişti.", "tone": str(_get(current, "structure", "tone", default="warning"))}]


def _regime_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = str(_get(previous, "regime", "state", default="—"))
    after = str(_get(current, "regime", "state", default="—"))
    if before == after:
        return []
    return [{"field": "Rejim", "text": f"Rejim {before} → {after} olarak değişti.", "tone": "warning"}]


def _position_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = str(_get(previous, "profile", "position", default="—"))
    after = str(_get(current, "profile", "position", default="—"))
    if before == after:
        return []
    return [{"field": "Konum", "text": f"Fiyat {before.casefold()} konumundan {after.casefold()} konumuna geçti.", "tone": str(_get(current, "profile", "tone", default="neutral"))}]


def _trend_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = str(_get(previous, "semantic", "trend_quality", "state", default="—"))
    after = str(_get(current, "semantic", "trend_quality", "state", default="—"))
    if before == after:
        return []
    return [{"field": "Trend", "text": f"EMA dizilimi: {before} → {after}.", "tone": str(_get(current, "semantic", "trend_quality", "tone", default="warning"))}]


def _momentum_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = str(_get(previous, "semantic", "momentum_character", "state", default="—"))
    after = str(_get(current, "semantic", "momentum_character", "state", default="—"))
    if before == after:
        return []
    return [{"field": "Momentum", "text": f"Momentum karakteri: {before} → {after}.", "tone": str(_get(current, "semantic", "momentum_character", "tone", default="warning"))}]


def _participation_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before_state = str(_get(previous, "setup_context", "participation_reading", "state", default="—"))
    after_state = str(_get(current, "setup_context", "participation_reading", "state", default="—"))
    before_rvol = _number(_get(previous, "semantic", "participation", "rvol_1"))
    after_rvol = _number(_get(current, "semantic", "participation", "rvol_1"))
    items: list[dict[str, str]] = []
    if before_state != after_state and "—" not in (before_state, after_state):
        items.append({"field": "Katılım", "text": f"Katılım okuması: {before_state} → {after_state}.", "tone": str(_get(current, "setup_context", "participation_reading", "tone", default="neutral"))})
    elif math.isfinite(before_rvol) and math.isfinite(after_rvol) and before_rvol > 0:
        ratio = after_rvol / before_rvol
        if ratio >= 1.5 or ratio <= 0.67:
            direction = "arttı" if ratio > 1 else "azaldı"
            items.append({"field": "Katılım", "text": f"RVOL belirgin biçimde {direction}: {before_rvol:.2f}x → {after_rvol:.2f}x.", "tone": "warning"})
    return items


def _duration_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = int(_number(_get(previous, "setup_context", "duration", "squeeze_bars"), 0))
    after = int(_number(_get(current, "setup_context", "duration", "squeeze_bars"), 0))
    if before >= 3 and after == 0:
        return [{"field": "Sıkışma", "text": f"{before} bardır süren dar bant bölgesinden çıkıldı.", "tone": "warning"}]
    if before == 0 and after >= 3:
        return [{"field": "Sıkışma", "text": f"Dar bant bölgesine girildi ({after} bar).", "tone": "warning"}]
    return []


def _relative_strength_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = _number(_get(previous, "relative_strength", "ratio_slope_5_pct"))
    after = _number(_get(current, "relative_strength", "ratio_slope_5_pct"))
    if not (math.isfinite(before) and math.isfinite(after)):
        return []
    if (before < 0 <= after) or (before >= 0 > after):
        direction = "güçlenmeye" if after >= 0 else "zayıflamaya"
        return [{"field": "Göreceli güç", "text": f"Benchmarka göre eğilim {direction} döndü (rasyo eğimi %{before:+.2f} → %{after:+.2f}).", "tone": "positive" if after >= 0 else "negative"}]
    return []


def _clarity_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = str(previous.get("clarity_state", "—"))
    after = str(current.get("clarity_state", "—"))
    if before == after or "—" in (before, after):
        return []
    return [{"field": "Netlik", "text": f"Teknik okuma netliği {before} → {after} oldu.", "tone": "neutral"}]


def _level_change(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    before = _get(previous, "semantic", "level_confluence", "clusters", default=[]) or []
    after = _get(current, "semantic", "level_confluence", "clusters", default=[]) or []
    if not before or not after:
        return []
    before_side = str(before[0].get("side", ""))
    after_side = str(after[0].get("side", ""))
    if before_side and after_side and before_side != after_side:
        low, high = _number(after[0].get("low")), _number(after[0].get("high"))
        span = _fmt(low) if abs(high - low) < 0.005 else f"{_fmt(low)}–{_fmt(high)}"
        return [{
            "field": "Seviye",
            "text": f"En yakın yoğunlaşma bölgesi {before_side} iken {after_side} tarafa geçti ({span}).",
            "tone": "warning",
        }]
    return []


COMPARATORS = (
    _setup_change,
    _bias_change,
    _structure_change,
    _regime_change,
    _position_change,
    _duration_change,
    _trend_change,
    _momentum_change,
    _participation_change,
    _relative_strength_change,
    _level_change,
    _clarity_change,
)


def compare_states(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    """Dünkü ve bugünkü durumu karşılaştırıp anlamlı değişimleri listeler."""
    if not previous:
        return {
            "available": False,
            "items": [],
            "bullets": ["Önceki bar durumu hesaplanamadı; karşılaştırma yapılamıyor."],
            "method": "Karşılaştırma için en az iki tamamlanmış bar gerekir.",
        }
    items: list[dict[str, str]] = []
    for comparator in COMPARATORS:
        items.extend(comparator(previous, current))
    bullets = [item["text"] for item in items[:BULLETS_LIMIT]]
    if not bullets:
        bullets = ["Ana teknik sınıflamalarda düne göre değişiklik yok; kurulum, yapı, rejim ve konum aynı."]
    return {
        "available": True,
        "items": items[:BULLETS_LIMIT],
        "bullets": bullets,
        "method": "Son bar çıkarılarak aynı hesap yeniden çalıştırılır; iki durum alan alan karşılaştırılır.",
    }
