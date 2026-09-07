"""Tarama zamanlayıcısı.

GitHub'ın zamanlanmış koşuları bu depoda güvenilir çalışmadığı için tarama,
sürekli çalışan bot süreci tarafından tetiklenir. Bot saati kendisi kontrol
eder; bir slot geçildiyse ilgili aralıklarla taramayı başlatır ve hangi slotu
çalıştırdığını diske yazarak aynı slotu iki kez tetiklemez.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("Europe/Istanbul")
STATE_PATH = Path("reports/scan_schedule.json")
# Slotun kaçırılmış sayılmadan önce beklenebilecek en uzun süre.
GRACE_MINUTES = 45


@dataclass(frozen=True)
class Slot:
    hour: int
    minute: int
    intervals: str

    @property
    def key(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


# Hızlı dilimler seans içinde, yavaş dilimler kapanışta.
SLOTS = (
    Slot(10, 30, "1h,4h"),
    Slot(12, 30, "1h,4h"),
    Slot(14, 30, "1h,4h"),
    Slot(17, 30, "1h,4h"),
    Slot(19, 30, "1d,1wk,1mo"),
)


def now_market() -> datetime:
    return datetime.now(MARKET_TIMEZONE)


def load_state(path: Path = STATE_PATH) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in payload.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def save_state(state: dict[str, str], path: Path = STATE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def due_slot(current: datetime, state: dict[str, str]) -> Slot | None:
    """Şu an tetiklenmesi gereken slot varsa döndürür.

    Hafta sonları çalışmaz. Slot saati geçmişse ve bugün henüz çalıştırılmadıysa
    tetiklenir; gecikme toleransı aşılmışsa slot atlanır, böylece uzun bir
    kesintiden sonra geçmiş slotların hepsi arka arkaya çalışmaz.
    """
    if current.weekday() >= 5:
        return None
    today = current.date().isoformat()
    for slot in SLOTS:
        if state.get(slot.key) == today:
            continue
        scheduled = current.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        if current < scheduled:
            continue
        if (current - scheduled).total_seconds() / 60 > GRACE_MINUTES:
            continue
        return slot
    return None


def mark_done(slot: Slot, current: datetime, state: dict[str, str]) -> dict[str, str]:
    updated = dict(state)
    updated[slot.key] = current.date().isoformat()
    return updated

# Seans sonrası koşuların sınırı; bu saatten sonra yavaş dilimler taranır.
CLOSE_HOUR = 18


def resolve_intervals(value: str, current: datetime | None = None) -> str:
    """'auto' değerini saate göre gerçek aralık listesine çevirir.

    Aralık seçimi daha önce iş akışı dosyasındaki koşullu ifadeyle yapılıyordu;
    orası test edilemediği için sessizce boş dönüp varsayılana düşebiliyordu.
    Karar burada verilir ve testlerle sabitlenir.
    """
    cleaned = (value or "").strip()
    if cleaned and cleaned.lower() != "auto":
        return cleaned
    moment = current or now_market()
    if moment.hour >= CLOSE_HOUR:
        return SLOTS[-1].intervals
    return SLOTS[0].intervals
