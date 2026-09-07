"""Bot ayarları.

Tarama eşikleri Telegram komutlarıyla değiştirilebilir ve diske yazılır; böylece
her tarama tetiklendiğinde aynı değerler kullanılır. Ayarlar iş akışı girdisi
olarak geçirildiği için tarama davranışı kod değişikliği gerektirmeden ayarlanır.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SETTINGS_PATH = Path("reports/bot_settings.json")


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    workflow_input: str
    minimum: float
    maximum: float
    default: float
    digits: int = 2


# Komutla ayarlanabilen eşikler. Sınırlar, anlamsız değerlerin taramayı
# kullanılamaz hale getirmesini engeller (ör. RVOL 0 her sembolü eşleştirir).
SETTINGS: dict[str, Setting] = {
    "rvol": Setting("rvol", "Minimum RVOL (sıkışma + hacim)", "rvol_min", 0.5, 10.0, 1.5),
    "patlama": Setting("patlama", "Hacim patlaması eşiği", "rvol_spike", 1.5, 20.0, 3.0),
    "bant": Setting("bant", "Bollinger genişlik yüzdeliği üst sınırı", "bb_rank_max", 1.0, 100.0, 20.0, 0),
    "hacim": Setting("hacim", "Minimum 20 bar ortalama TL hacmi", "min_turnover", 1_000_000.0, 1_000_000_000.0, 20_000_000.0, 0),
    "rapor": Setting("rapor", "Kaç yeni eşleşme için tam rapor üretilsin", "report_top", 0.0, 5.0, 3.0, 0),
}

ALIASES = {
    "rvol_min": "rvol",
    "hacim_patlamasi": "patlama",
    "spike": "patlama",
    "bb": "bant",
    "bollinger": "bant",
    "likidite": "hacim",
    "turnover": "hacim",
    "report_top": "rapor",
}


def defaults() -> dict[str, float]:
    return {name: setting.default for name, setting in SETTINGS.items()}


def load_settings(path: Path = SETTINGS_PATH) -> dict[str, float]:
    """Kayıtlı ayarları okur; bozuk veya eksik alanlar varsayılana döner."""
    values = defaults()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return values
    if not isinstance(payload, dict):
        return values
    for name, setting in SETTINGS.items():
        raw = payload.get(name)
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        if setting.minimum <= number <= setting.maximum:
            values[name] = number
    return values


def save_settings(values: dict[str, float], path: Path = SETTINGS_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def normalize_key(name: str) -> str | None:
    cleaned = name.strip().casefold()
    cleaned = ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in SETTINGS else None


def apply_change(values: dict[str, float], name: str, raw_value: str) -> tuple[dict[str, float] | None, str]:
    """Tek bir eşiği değiştirir; geçersizse nedenini döndürür."""
    key = normalize_key(name)
    if key is None:
        return None, f"Bilinmeyen eşik: {name}. Geçerli olanlar: {', '.join(SETTINGS)}"
    setting = SETTINGS[key]
    try:
        number = float(raw_value.replace(",", "."))
    except ValueError:
        return None, f"Sayı bekleniyordu: {raw_value}"
    if not setting.minimum <= number <= setting.maximum:
        return None, f"{setting.label} için geçerli aralık {setting.minimum:g} – {setting.maximum:g}."
    updated = dict(values)
    updated[key] = number
    return updated, f"{setting.label} artık {number:,.{setting.digits}f}."


def describe(values: dict[str, float]) -> str:
    lines = ["Geçerli tarama eşikleri:"]
    for name, setting in SETTINGS.items():
        marker = "" if values[name] == setting.default else "  (değiştirildi)"
        lines.append(f"/{name} = {values[name]:,.{setting.digits}f} — {setting.label}{marker}")
    lines.append("")
    lines.append("Değiştirmek için: /esik rvol 2.0   ·   Varsayılana dönmek için: /esik sifirla")
    return "\n".join(lines)


def workflow_inputs(values: dict[str, float]) -> dict[str, str]:
    """Ayarları iş akışı girdisi biçimine çevirir."""
    inputs: dict[str, str] = {}
    for name, setting in SETTINGS.items():
        inputs[setting.workflow_input] = f"{values[name]:.{setting.digits}f}"
    return inputs
