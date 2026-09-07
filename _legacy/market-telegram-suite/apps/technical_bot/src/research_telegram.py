"""Telegram delivery for the integrated research report."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

from src.research_commentary_advanced import commentary_messages
from src.research_engine import ResearchReport
from src.telegram_client import CAPTION_LIMIT, DEFAULT_CHAT_ID, caption_enabled, clip


def _destination() -> tuple[str, str, str]:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID).strip()
    thread_id = os.getenv("TELEGRAM_MESSAGE_THREAD_ID", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN GitHub Actions Secret olarak tanımlanmalıdır.")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID GitHub Actions Secret olarak tanımlanmalıdır.")
    return token, chat_id, thread_id


def _caption(report: ResearchReport) -> str:
    score = "—" if report.research_score is None else f"{report.research_score:.0f}/100"
    risk = "—" if report.main_risk is None else f"{report.main_risk.name} ({report.main_risk.score:.0f}/100)"
    financial = report.financial
    structure = report.technical.get("structure", {})
    hierarchy = report.technical.get("structure_hierarchy", {})
    elliott = report.technical.get("elliott", {})
    valuation = report.valuation or {}
    lines = [
        f"📚 {report.symbol} — Araştırma Özeti",
        f"Genel durum: {score} · veri kapsamı %{round(report.coverage * 100)}",
        f"Bilanço: {financial.get('balance_label', '—')} · Kâr kalitesi: {financial.get('earnings_quality_label', '—')}",
        f"Değerleme yöntemi: {valuation.get('primary_model', '—')} · model güveni %{round(float(valuation.get('model_confidence') or 0.0) * 100)}",
        f"Borç yönü: {financial.get('debt_direction', '—')}",
        f"Teknik: {report.technical.get('label', '—')} · {structure.get('event', structure.get('bos', '—'))}",
        f"Yapı hiyerarşisi: {hierarchy.get('summary', '—')} · teyitli rail {hierarchy.get('confirmed_rails', 0)}",
        f"Elliott bağlamı: {elliott.get('primary', '—')} · güven %{elliott.get('confidence', '—')}",
        f"Ana risk: {risk}",
        "",
        "Önce altı görsel, ardından bölüm bölüm analist yorumu gelir. Otomatik AL/SAT değildir.",
    ]
    return clip("\n".join(lines), CAPTION_LIMIT)


def _verified_message(response_payload: dict[str, Any], expected_thread_id: str) -> dict[str, Any]:
    if response_payload.get("ok") is not True:
        raise RuntimeError("Telegram Bot API ok=true dönmedi.")
    result = response_payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("message_id"), int):
        raise TypeError("Telegram gönderiminde message_id doğrulanamadı.")
    if expected_thread_id:
        actual_thread = result.get("message_thread_id")
        if str(actual_thread) != str(expected_thread_id):
            raise RuntimeError(
                f"Telegram topic doğrulaması başarısız: beklenen={expected_thread_id}, gerçek={actual_thread}."
            )
    return response_payload


def _decode_response(response: requests.Response, thread_id: str, *, context: str) -> dict[str, Any]:
    if not response.ok:
        raise RuntimeError(
            f"Telegram {context} gönderimi başarısız: HTTP {response.status_code} — {response.text[:300]}"
        )
    try:
        decoded = dict(response.json())
    except ValueError as exc:
        raise RuntimeError("Telegram yanıtı JSON olarak çözülemedi.") from exc
    return _verified_message(decoded, thread_id)


def _send_photo(
    token: str,
    chat_id: str,
    thread_id: str,
    image_path: Path,
    caption: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_id": chat_id}
    if thread_id:
        payload["message_thread_id"] = thread_id
    if caption and caption_enabled():
        payload["caption"] = clip(caption, CAPTION_LIMIT)
    with image_path.open("rb") as image:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendPhoto",
            data=payload,
            files={"photo": (image_path.name, image, "image/png")},
            timeout=60,
        )
    return _decode_response(response, thread_id, context="araştırma görseli")


def _send_text(token: str, chat_id: str, thread_id: str, text: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if thread_id:
        payload["message_thread_id"] = thread_id
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        timeout=60,
    )
    return _decode_response(response, thread_id, context="analist yorumu")


def send_research_bundle(
    summary_card: Path,
    fundamental_card: Path,
    financial_card: Path,
    valuation_peer_card: Path,
    moving_average_card: Path,
    technical_chart: Path,
    report: ResearchReport,
) -> tuple[dict[str, Any], ...]:
    """Send six visuals first, then analyst paragraphs, with topic verification."""
    token, chat_id, thread_id = _destination()
    results: list[dict[str, Any]] = [
        _send_photo(token, chat_id, thread_id, summary_card, _caption(report)),
        _send_photo(
            token,
            chat_id,
            thread_id,
            fundamental_card,
            f"{report.symbol} · Temel analiz / sektör profili",
        ),
        _send_photo(
            token,
            chat_id,
            thread_id,
            financial_card,
            f"{report.symbol} · Finansal oranlar / forensic skorlar",
        ),
        _send_photo(
            token,
            chat_id,
            thread_id,
            valuation_peer_card,
            f"{report.symbol} · Ham-öncelikli değerleme / sektör-rakip karşılaştırması",
        ),
        _send_photo(
            token,
            chat_id,
            thread_id,
            moving_average_card,
            f"{report.symbol} · Günlük MA 5/8/13 · 21/34/55 · 89/144/233",
        ),
        _send_photo(
            token,
            chat_id,
            thread_id,
            technical_chart,
            f"{report.symbol} · Fiyat + Hacim + Yapı + BB + AlphaTrend + MACD + SMI + RSI Divergence + OBV + ATR",
        ),
    ]
    results.extend(_send_text(token, chat_id, thread_id, message) for message in commentary_messages(report))
    return tuple(results)
