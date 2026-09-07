"""Telegram komut botu.

GitHub Actions sürekli çalışan bir sunucu sunmadığı için bot, webhook yerine
belirli aralıklarla `getUpdates` çağırarak yeni mesajları toplar. Bu nedenle
komutlara yanıt anlık değil, en fazla yoklama aralığı kadar gecikmeyle gelir.

İşlenen son mesaj kimliği diske yazılır; aynı komut iki kez çalıştırılmaz.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

OFFSET_PATH = Path("reports/telegram_offset.json")
COMMAND_PATTERN = re.compile(r"^/(?P<command>[a-zA-ZğüşıöçĞÜŞİÖÇ]+)(?:@\S+)?(?P<args>.*)$", re.DOTALL)
VALID_TICKER = re.compile(r"^[A-Z0-9]{4,6}$")

HELP_TEXT = (
    "Kullanılabilir komutlar:\n"
    "/tara [aralık] — yeni tarama başlatır (boşsa saate göre seçilir)\n"
    "/liste — son tamamlanan taramanın tam listesi\n"
    "/gecmis [no] — geçmiş taramalar (numarasız: liste)\n"
    "/takip SEMBOL [aralık] — teyitli yapı seviyelerini izler\n"
    "/takip sil SEMBOL — takipten çıkarır\n"
    "/esik [ad değer] — tarama eşikleri (ör. /esik rvol 2.0)\n"
    "/durum — bot ve tarama durumu\n"
    "/yardim — bu mesaj\n\n"
    "Geçerli aralıklar: 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1wk, 1mo"
)


@dataclass(frozen=True)
class Command:
    name: str
    args: list[str]
    chat_id: int
    user_id: int
    user_name: str
    update_id: int
    message_thread_id: int | None = None


def load_offset(path: Path = OFFSET_PATH) -> int:
    """En son işlenen güncelleme kimliği; tekrar işlemeyi önler."""
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["offset"])
    except (OSError, ValueError, KeyError, TypeError):
        return 0


def save_offset(offset: int, path: Path = OFFSET_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"offset": int(offset)}), encoding="utf-8")
    except OSError:
        pass


def parse_command(update: dict[str, Any]) -> Command | None:
    """Telegram güncellemesinden komutu çıkarır; komut değilse None."""
    message = update.get("message") or update.get("channel_post") or {}
    text = str(message.get("text", "")).strip()
    if not text.startswith("/"):
        return None
    match = COMMAND_PATTERN.match(text)
    if not match:
        return None
    sender = message.get("from") or {}
    return Command(
        name=match.group("command").casefold(),
        args=match.group("args").split(),
        chat_id=int(message.get("chat", {}).get("id", 0)),
        user_id=int(sender.get("id", 0)),
        user_name=str(sender.get("username") or sender.get("first_name") or "bilinmiyor"),
        update_id=int(update.get("update_id", 0)),
        message_thread_id=(
            int(message["message_thread_id"])
            if message.get("message_thread_id") is not None
            else None
        ),
    )


def allowed_users() -> set[int]:
    """Boş bırakılırsa herkes komut verebilir; aksi halde yalnızca listedekiler."""
    raw = os.getenv("TELEGRAM_ALLOWED_USERS", "").strip()
    if not raw:
        return set()
    return {int(item) for item in re.split(r"[,\s]+", raw) if item.strip().isdigit()}


def is_authorized(command: Command, allowed: set[int]) -> bool:
    """Kullanıcı, sohbet ve forum konusu kısıtlarını birlikte uygular."""
    if allowed and command.user_id not in allowed:
        return False

    expected_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if expected_chat:
        try:
            if command.chat_id != int(expected_chat):
                return False
        except ValueError:
            return False

    expected_thread = os.getenv("TELEGRAM_MESSAGE_THREAD_ID", "").strip()
    if expected_thread:
        try:
            if command.message_thread_id != int(expected_thread):
                return False
        except ValueError:
            return False

    return True


def fetch_updates(token: str, offset: int, timeout: int = 10, long_poll: int = 0) -> list[dict[str, Any]]:
    """Yeni güncellemeleri çeker.

    `long_poll` saniye verilirse Telegram bağlantıyı o süre açık tutar ve mesaj
    gelir gelmez döner. Böylece komutlara saniyeler içinde yanıt verilebilir;
    GitHub Actions'ın sık zamanlanmış koşuları güvenilir çalışmadığı için tek
    koşu içinde sürekli dinlemek tek pratik yöntemdir.
    """
    response = requests.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={"offset": offset + 1, "timeout": long_poll, "allowed_updates": json.dumps(["message"])},
        timeout=timeout + long_poll,
    )
    if not response.ok:
        raise RuntimeError(f"getUpdates başarısız: HTTP {response.status_code} — {response.text[:200]}")
    payload = response.json()
    return list(payload.get("result", []))


def validate_report_args(
    args: list[str],
    intervals: set[str],
    command: str = "rapor",
) -> tuple[str | None, str, str | None]:
    """Sembol + opsiyonel aralık argümanlarını doğrular."""
    example = f"/{command} THYAO"
    if not args:
        return None, "", f"Sembol belirtilmedi. Örnek: {example}"
    if len(args) > 2:
        return None, "", f"Fazla argüman. Kullanım: {example} [aralık]"
    ticker = args[0].strip().upper().removesuffix(".IS")
    if not VALID_TICKER.match(ticker):
        return None, "", f"Geçersiz sembol: {args[0]}. Örnek: {example}"
    interval = args[1].strip().lower() if len(args) > 1 else "1d"
    if interval not in intervals:
        return None, "", f"Geçersiz aralık: {args[1]}. Geçerli değerler: {', '.join(sorted(intervals))}"
    return ticker, interval, None


def validate_scan_args(args: list[str], intervals: set[str]) -> tuple[str, str | None]:
    """/tara argümanlarını doğrular; (aralık listesi, hata) döndürür."""
    if not args:
        return "auto", None
    requested = [item.strip().lower() for item in args[0].split(",") if item.strip()]
    invalid = [item for item in requested if item not in intervals]
    if invalid:
        return "", f"Geçersiz aralık: {', '.join(invalid)}. Geçerli değerler: {', '.join(sorted(intervals))}"
    return ",".join(requested), None
