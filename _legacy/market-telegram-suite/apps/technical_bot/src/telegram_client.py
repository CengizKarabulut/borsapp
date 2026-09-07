from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

DEFAULT_CHAT_ID = "-1003502567927"
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


def clip(text: str, limit: int) -> str:
    """Telegram karakter sınırını aşan metni güvenli biçimde kısaltır."""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Uzun metni satır sınırlarını koruyarak Telegram mesaj sınırına böler."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            if current:
                parts.append(current)
            current = clip(line, limit)
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def build_caption(status: dict[str, Any]) -> str:
    context = status["market_context"]
    profile = context["profile"]
    structure = context["structure"]
    bar_state = status.get("bar_state", {"label": "BİLİNMİYOR"})
    decision = status.get("decision_context", {})
    rs = decision.get("relative_strength", {})
    mtf = decision.get("multi_timeframe", {})
    liquidity = decision.get("liquidity", {})
    commentary = status.get("technical_commentary", {})
    atr_percentile = context["regime"].get("atr_percentile")
    bb_percentile = context["regime"].get("bb_percentile")
    volatility = (
        f"ATR perc %{atr_percentile:.0f} | BB perc %{bb_percentile:.0f}"
        if atr_percentile is not None and bb_percentile is not None
        else "—"
    )
    lines = [
        f"📊 {status['symbol']} — Teknik Piyasa Durumu",
        f"Fiyat: {status['price']:,.2f} ({status['change_pct']:+.2f}%)",
        f"Mum: {bar_state.get('label', 'BİLİNMİYOR')} | Piyasa: {bar_state.get('market_state', '—')}",
        "",
        f"Rejim: {context['regime']['state']}",
        f"Yapı: {structure['state']} — {structure['event']}",
        f"Konum: {profile['position']} | {profile.get('developing_acceptance', profile.get('acceptance', '—'))}",
        f"Katılım: RVOL {context['relative_volume']:.2f}x",
        f"Volatilite: {volatility}",
    ]
    if rs.get("available"):
        lines.append(f"RS vs {rs['benchmark']}: {rs['state']}")
    if mtf:
        lines.append(f"MTF: {mtf.get('state', '—')}")
    if liquidity:
        lines.append(f"Likidite: {liquidity.get('state', '—')}")
    divergence_items = context.get("divergences", {}).get("indicators", {})
    active_divergences = [
        f"{name} {item['state']} ({item['event_age']} bar)"
        for name, item in divergence_items.items()
        if item.get("detected")
    ]
    if active_divergences:
        lines.append("Uyumsuzluk: " + " | ".join(active_divergences))
    if commentary.get("headline"):
        lines.extend(["", "Teknik yorum:", commentary["headline"]])
    lines.extend(
        [
            "",
            "Yaklaşık OHLCV Volume Profile:",
            f"POC {profile['poc']:,.2f} | VAH {profile['vah']:,.2f} | VAL {profile['val']:,.2f}",
            "Gerçek footprint/delta değildir.",
            f"Kaynak: {status.get('data_provider', 'bilinmiyor')}",
            f"Bar: {status['timestamp']}",
            "",
            "Durum raporudur; otomatik AL/SAT puanı değildir. Yatırım tavsiyesi değildir.",
        ]
    )
    return "\n".join(lines)


def _destination() -> tuple[str, str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID).strip()
    thread_id = os.getenv("TELEGRAM_MESSAGE_THREAD_ID", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN GitHub Actions Secret olarak tanımlanmalıdır.")
    return token, chat_id, thread_id


def send_photo(image_path: Path, status: dict[str, Any]) -> None:
    token, chat_id, thread_id = _destination()
    payload: dict[str, Any] = {"chat_id": chat_id}
    if caption_enabled():
        payload["caption"] = clip(build_caption(status), CAPTION_LIMIT)
    if thread_id:
        payload["message_thread_id"] = thread_id
    with image_path.open("rb") as image:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=payload,
            files={"photo": (image_path.name, image, "image/png")},
            timeout=60,
        )
    if not response.ok:
        raise RuntimeError(f"Telegram gönderimi başarısız: HTTP {response.status_code} — {response.text[:300]}")


def caption_enabled() -> bool:
    """Görsel altı açıklama varsayılan olarak kapalıdır; tüm bilgi görselin içindedir."""
    return os.getenv("TELEGRAM_SEND_CAPTION", "0").strip().lower() in {"1", "true", "yes", "evet"}


def text_detail_enabled() -> bool:
    """Ayrıntılı metin mesajı varsayılan olarak kapalıdır; kart görseli onun yerini alır."""
    return os.getenv("TELEGRAM_SEND_TEXT_DETAIL", "0").strip().lower() in {"1", "true", "yes", "evet"}


def send_report_detail(status: dict[str, Any]) -> bool:
    """Ayrıntılı analist notunu düz metin olarak gönderir (yalnızca açıkça istendiğinde)."""
    commentary = status.get("technical_commentary", {})
    detail = str(commentary.get("telegram_detail", "")).strip()
    if not detail or not text_detail_enabled():
        return False
    header = f"📝 {status.get('symbol', '—')} — Ayrıntılı Teknik Okuma ({status.get('timestamp', '—')})"
    send_text(f"{header}\n\n{detail}")
    return True


def card_caption(status: dict[str, Any]) -> str:
    """Analist kartı için kısa açıklama; ayrıntı görselin içindedir."""
    commentary = status.get("technical_commentary", {})
    setup = commentary.get("setup", {})
    clarity = commentary.get("clarity", {})
    lines = [
        f"🗣️ {status.get('symbol', '—')} — Analist Kartı",
        f"Kurulum: {setup.get('name', '—')} ({setup.get('bias', '—')})",
        f"Okuma netliği: {clarity.get('state', '—')}",
        "",
        "Ayrıntılı okuma görselin içindedir. Yatırım tavsiyesi değildir.",
    ]
    return clip("\n".join(lines), CAPTION_LIMIT)


def send_report_pages(image_paths: list[Path], status: dict[str, Any]) -> int:
    """Teknik rapor sayfalarını sırayla gönderir."""
    for path in image_paths:
        send_photo(path, status)
    return len(image_paths)


def send_analyst_cards(image_paths: list[Path], status: dict[str, Any]) -> int:
    """Kart sayfalarını sırayla gönderir ve gönderilen sayıyı döndürür."""
    for path in image_paths:
        send_analyst_card(path, status)
    return len(image_paths)


def send_analyst_card(image_path: Path, status: dict[str, Any]) -> None:
    """Analist kartını ikinci fotoğraf olarak gönderir."""
    token, chat_id, thread_id = _destination()
    payload: dict[str, Any] = {"chat_id": chat_id}
    if caption_enabled():
        payload["caption"] = card_caption(status)
    if thread_id:
        payload["message_thread_id"] = thread_id
    with image_path.open("rb") as image:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=payload,
            files={"photo": (image_path.name, image, "image/png")},
            timeout=60,
        )
    if not response.ok:
        raise RuntimeError(f"Telegram kart gönderimi başarısız: HTTP {response.status_code} — {response.text[:300]}")


def send_text(text: str) -> None:
    for part in split_message(text):
        _send_single_text(part)


def _send_single_text(text: str) -> None:
    token, chat_id, thread_id = _destination()
    payload = {"chat_id": chat_id, "text": text}
    if thread_id:
        payload["message_thread_id"] = thread_id
    response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, timeout=60)
    if not response.ok:
        raise RuntimeError(f"Telegram gönderimi başarısız: HTTP {response.status_code} — {response.text[:300]}")
