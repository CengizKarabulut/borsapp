"""Telegram sender dedicated to the fundamental scorecard."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

from src.fundamental_analysis import FundamentalReport
from src.telegram_client import CAPTION_LIMIT, DEFAULT_CHAT_ID, caption_enabled, clip


def _destination() -> tuple[str, str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID).strip()
    thread_id = os.getenv("TELEGRAM_MESSAGE_THREAD_ID", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN GitHub Actions Secret olarak tanımlanmalıdır.")
    return token, chat_id, thread_id


def _caption(report: FundamentalReport) -> str:
    score = "—" if report.overall_score is None else f"{report.overall_score:.2f}/5"
    lines = [
        f"🏦 {report.symbol} — Temel Analiz",
        f"Genel skor: {score}",
        f"Profil: {report.profile} · veri kapsamı %{round(report.coverage * 100)}",
        "",
        "Ayrıntılı temel okuma görselin içindedir. Yatırım tavsiyesi değildir.",
    ]
    return clip("\n".join(lines), CAPTION_LIMIT)


def send_fundamental_card(image_path: Path, report: FundamentalReport) -> dict[str, Any]:
    """Send one PNG to the configured technical-analysis Telegram topic."""
    token, chat_id, thread_id = _destination()
    payload: dict[str, Any] = {"chat_id": chat_id}
    if caption_enabled():
        payload["caption"] = _caption(report)
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
        raise RuntimeError(
            f"Telegram temel analiz gönderimi başarısız: HTTP {response.status_code} — {response.text[:300]}"
        )
    try:
        return dict(response.json())
    except ValueError:
        return {"ok": True}
