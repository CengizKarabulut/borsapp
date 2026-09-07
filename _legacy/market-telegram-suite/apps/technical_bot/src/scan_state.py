"""Tarama tekrar durumu.

Saatlik tarama aynı hisseyi gün boyu yeniden eşleştirir. Tam rapor her seferinde
üretilirse kanal aynı dört sayfayla dolar. Bu modül, gün içinde hangi sembol
hangi tarama bileşimiyle raporlandığını saklar; yalnızca yeni bir durum ortaya
çıktığında rapor üretilmesini sağlar.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

STATE_PATH = Path("reports/scan_state.json")
# Gün sınırı borsa saatiyle belirlenir; UTC kullanılırsa seans ortasında sıfırlanır.
MARKET_TIMEZONE = ZoneInfo("Europe/Istanbul")


def market_today() -> str:
    return datetime.now(MARKET_TIMEZONE).date().isoformat()


def _signature(item: dict[str, Any]) -> str:
    """Sembolün o günkü 'durumu': eşleşen taramalar ve kurulum adı."""
    screens = ",".join(sorted(item.get("screens", [])))
    return f"{screens}|{item.get('setup', '')}"


def load_state(path: Path = STATE_PATH, today: str | None = None) -> dict[str, str]:
    """Bugüne ait kayıtları okur; tarih değiştiyse durum sıfırlanır."""
    stamp = today or market_today()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if payload.get("date") != stamp:
        return {}
    reported = payload.get("reported", {})
    return {str(key): str(value) for key, value in reported.items()} if isinstance(reported, dict) else {}


def save_state(reported: dict[str, str], path: Path = STATE_PATH, today: str | None = None) -> None:
    stamp = today or market_today()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"date": stamp, "reported": reported}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def select_new(results: list[dict[str, Any]], reported: dict[str, str], limit: int) -> list[dict[str, Any]]:
    """Bugün henüz raporlanmamış veya durumu değişmiş sembolleri seçer."""
    if limit <= 0:
        return []
    fresh = []
    for item in results:
        ticker = str(item.get("ticker", ""))
        if not ticker:
            continue
        if reported.get(ticker) == _signature(item):
            continue
        fresh.append(item)
        if len(fresh) >= limit:
            break
    return fresh


def mark_reported(items: list[dict[str, Any]], reported: dict[str, str]) -> dict[str, str]:
    updated = dict(reported)
    for item in items:
        ticker = str(item.get("ticker", ""))
        if ticker:
            updated[ticker] = _signature(item)
    return updated
