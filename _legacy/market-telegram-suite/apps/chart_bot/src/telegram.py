"""Telegram teslimati.

PNG fotograf olarak, etkilesimli HTML ise dosya (document) olarak gonderilir.
Ortam degiskenleri:
    TELEGRAM_BOT_TOKEN   zorunlu
    TELEGRAM_CHAT_ID     zorunlu (grup icin -100... ile baslar)
    TELEGRAM_TOPIC_ID    istege bagli; forum modundaki gruplarda konu numarasi

Konu numarasi web.telegram.org adresindeki baglantinin sonundaki sayidir:
    https://web.telegram.org/a/#-1003502567927_18
                                 ^chat id     ^konu
Verilmezse mesaj grubun genel akisina duser, konuya degil.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

API = "https://api.telegram.org/bot{token}/{method}"
CAPTION_LIMIT = 1024


class TelegramError(RuntimeError):
    pass


def _credentials() -> tuple[str, str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    topic_id = os.environ.get("TELEGRAM_TOPIC_ID", "").strip()
    missing = [name for name, value in
               (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id))
               if not value]
    if missing:
        raise TelegramError(
            f"Eksik ortam degiskeni: {', '.join(missing)}\n"
            "GitHub Actions'ta bu, ayni adli secret'in tanimli olmadigi anlamina "
            "gelir: Settings -> Secrets and variables -> Actions -> New repository secret.\n"
            "Yerelde: $env:TELEGRAM_BOT_TOKEN = \"...\" (PowerShell)"
        )
    return token, chat_id, topic_id


def _post(method: str, files: dict | None, data: dict, timeout: int = 60) -> dict:
    token, chat_id, topic_id = _credentials()
    data = {"chat_id": chat_id, **data}
    # Cevap verilen mesajin konusu varsa o oncelikli; yoksa ortam degiskeni
    if not data.get("message_thread_id") and topic_id:
        data["message_thread_id"] = topic_id
    data = {k: v for k, v in data.items() if v is not None}
    response = requests.post(
        API.format(token=token, method=method), data=data, files=files, timeout=timeout
    )
    payload = response.json() if response.content else {}
    if not payload.get("ok"):
        raise TelegramError(f"{method} basarisiz: {response.status_code} {payload}")
    return payload


def send_message(text: str, thread_id: str | None = None) -> dict:
    """Duz metin mesaj. Bot komutlarina cevap vermek icin."""
    return _post("sendMessage", files=None,
                 data={"text": text[:4000], "parse_mode": "HTML",
                       "message_thread_id": thread_id})


def send_photo(path: str | Path, caption: str = "",
               thread_id: str | None = None) -> dict:
    _credentials()  # eksik token hatasi, dosya hatasindan once verilsin
    path = Path(path)
    with path.open("rb") as handle:
        return _post(
            "sendPhoto",
            files={"photo": (path.name, handle, "image/png")},
            data={"caption": caption[:CAPTION_LIMIT], "parse_mode": "HTML",
                  "message_thread_id": thread_id},
        )


def send_document(path: str | Path, caption: str = "",
                  thread_id: str | None = None) -> dict:
    _credentials()
    path = Path(path)
    mime = "image/png" if path.suffix.lower() == ".png" else "text/html"
    with path.open("rb") as handle:
        return _post(
            "sendDocument",
            files={"document": (path.name, handle, mime)},
            data={"caption": caption[:CAPTION_LIMIT], "parse_mode": "HTML",
                  "message_thread_id": thread_id},
        )


def send_media_group(paths: list[str | Path], caption: str = "") -> dict:
    """Birden fazla PNG'yi tek albüm olarak gonderir (Telegram siniri 10).

    Seri halinde gonderilen kareler boylece sohbette dagilmaz; basligi yalnizca
    ilk gorsel tasir.
    """
    _credentials()
    paths = [Path(p) for p in paths]
    if not paths:
        raise TelegramError("Gonderilecek gorsel yok")
    if len(paths) > 10:
        raise TelegramError(f"Albume en fazla 10 gorsel konabilir ({len(paths)} verildi)")

    handles, files, media = [], {}, []
    try:
        for i, path in enumerate(paths):
            handle = path.open("rb")
            handles.append(handle)
            tag = f"file{i}"
            files[tag] = (path.name, handle, "image/png")
            item = {"type": "photo", "media": f"attach://{tag}"}
            if i == 0 and caption:
                item["caption"] = caption[:CAPTION_LIMIT]
                item["parse_mode"] = "HTML"
            media.append(item)
        return _post("sendMediaGroup", files=files,
                     data={"media": json.dumps(media)}, timeout=120)
    finally:
        for handle in handles:
            handle.close()


_ME: dict[str, str] = {}


def get_me() -> str:
    """Botun kullanici adini dondurur (onbellekli).

    Grupta birden fazla bot varsa "/yardim@BotAdi" ile hedef secilir; kendi
    adimizi bilmeden bize mi yazildigini anlayamayiz.
    """
    if "username" in _ME:
        return _ME["username"]
    token, _, _ = _credentials()
    try:
        response = requests.get(API.format(token=token, method="getMe"), timeout=20)
        payload = response.json() if response.content else {}
        _ME["username"] = str(payload.get("result", {}).get("username", "")).lower()
    except Exception:  # noqa: BLE001 - ad ogrenilemezse adressiz komutlar yine calisir
        _ME["username"] = ""
    return _ME["username"]


def get_updates(offset: int | None = None, timeout: int = 30) -> list[dict]:
    """Uzun yoklama ile yeni mesajlari ceker.

    timeout saniyesi boyunca baglantiyi acik tutar; mesaj gelmezse bos liste
    doner. Bu, saniyede bir istek atmaktan cok daha verimlidir.
    """
    token, _, _ = _credentials()
    response = requests.get(
        API.format(token=token, method="getUpdates"),
        params={"offset": offset, "timeout": timeout,
                "allowed_updates": json.dumps(["message"])},
        timeout=timeout + 15,
    )
    payload = response.json() if response.content else {}
    if not payload.get("ok"):
        raise TelegramError(f"getUpdates basarisiz: {response.status_code} {payload}")
    return payload.get("result", [])


def build_caption(symbol: str, subtitle: str, chips: list[tuple[str, str, str]]) -> str:
    """PNG altinda gorunecek kisa ozet."""
    head = f"<b>{symbol}</b>\n<i>{subtitle}</i>"
    body = " · ".join(f"{label}: {value}" for label, value, _ in chips)
    return f"{head}\n{body}"
