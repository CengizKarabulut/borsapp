"""Route ATC visual scans to PRE-EXISTING Telegram timeframe topics.

No topic creation, no guessing numeric IDs and no fallback to generic SCANS.
IDs can already live in GitHub Actions variables/secrets or in one JSON mapping.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

from market_intelligence.core.identity import stable_hash
from market_intelligence.core.timeframes import Timeframe, parse_timeframe
from market_intelligence.delivery.telegram.config import TelegramSettings, TopicKind
from market_intelligence.delivery.telegram.routing import OutboxEnvelope, PublicationKind

TIMEFRAME_TOPICS = (
    Timeframe.M15, Timeframe.M30, Timeframe.M45,
    Timeframe.H1, Timeframe.H2, Timeframe.H4,
    Timeframe.D1, Timeframe.W1,
)
_ALIASES = {
    Timeframe.M15: "15M", Timeframe.M30: "30M", Timeframe.M45: "45M",
    Timeframe.H1: "1H", Timeframe.H2: "2H", Timeframe.H4: "4H",
    Timeframe.D1: "1D", Timeframe.W1: "1W",
}
# Message links in historical screenshots are NOT authoritative Bot API
# message_thread_id values. The prior inferred 1d=328 was rejected live with
# 'Bad Request: message thread not found' on 15 Oct 2026.
# Use only explicit existing-topic mapping supplied from GitHub vars/secrets.
_OLD_NAMES = {
    Timeframe.H1: ("60M", "60DK"), Timeframe.H2: ("120M", "120DK"),
    Timeframe.H4: ("240M", "240DK"), Timeframe.D1: ("DAILY", "GUNLUK"),
    Timeframe.W1: ("1WK", "WEEKLY", "HAFTALIK"),
}


def _topic_id(raw: object, description: str) -> int:
    try:
        value = int(str(raw).strip())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{description}: geçerli mevcut Telegram topic ID gerekli") from exc
    if value <= 0:
        raise ValueError(f"{description}: topic ID pozitif olmalı")
    return value


def timeframe_topic_ids(values: Mapping[str, str]) -> dict[Timeframe, int]:
    """Read stored mapping; never create a Telegram thread.

    Recommended existing variable names: TELEGRAM_TOPIC_15M, _30M, _45M,
    _1H, _2H, _4H, _1D, _1W. Compatible older names are also accepted.
    An optional TELEGRAM_TIMEFRAME_TOPICS JSON mapping overrides per-key vars.
    """
    mapping: dict[Timeframe, int] = {}
    raw_json = (values.get("TELEGRAM_TIMEFRAME_TOPICS") or "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise ValueError("TELEGRAM_TIMEFRAME_TOPICS JSON biçimi geçersiz") from exc
        if not isinstance(parsed, dict):
            raise ValueError("TELEGRAM_TIMEFRAME_TOPICS JSON nesnesi olmalı")
        for name, number in parsed.items():
            try:
                tf = parse_timeframe(str(name))
            except ValueError as exc:
                raise ValueError(f"Tanımsız zaman dilimi: {name}") from exc
            if tf not in TIMEFRAME_TOPICS:
                raise ValueError(f"Telegram görsel konu eşlemesi desteklenmiyor: {tf}")
            mapping[tf] = _topic_id(number, f"{tf} topic")
    for tf in TIMEFRAME_TOPICS:
        if tf in mapping:
            continue
        aliases = (_ALIASES[tf], *_OLD_NAMES.get(tf, ()))
        names = tuple(
            item for suffix in aliases for item in (
                f"TELEGRAM_TOPIC_{suffix}",
                f"TELEGRAM_TOPIC_SCAN_{suffix}",
                f"TELEGRAM_SCAN_TOPIC_{suffix}",
                f"TELEGRAM_{suffix}_TOPIC_ID",
                f"SCAN_{suffix}_TOPIC_ID",
            )
        )
        for key in names:
            raw = (values.get(key) or "").strip()
            if raw:
                mapping[tf] = _topic_id(raw, key)
                break
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Farklı zaman dilimleri aynı topic'e bağlı; eski eşleşmeyi doğrulayın")
    return mapping


def route_timeframe_image(
    settings: TelegramSettings,
    topic_ids: Mapping[Timeframe, int],
    timeframe: Timeframe,
    *,
    identity: dict,
    payload: dict,
) -> OutboxEnvelope:
    if timeframe not in topic_ids:
        raise ValueError(
            f"{timeframe.value} için KAYITLI Telegram topic ID bulunamadı. "
            "Genel tarama konusuna yanlışlıkla gönderim yapılmayacak."
        )
    thread_id = _topic_id(topic_ids[timeframe], timeframe.value)
    kind = PublicationKind.SCAN_EVENT
    semantic_key = stable_hash({
        "channel": "telegram",
        "publication_kind": kind,
        "semantic_identity": identity,
        "chat_id": settings.chat_id,
        "message_thread_id": thread_id,
    })
    return OutboxEnvelope(
        semantic_key=semantic_key, publication_kind=kind,
        topic_kind=TopicKind.SCANS,
        chat_id=settings.chat_id, message_thread_id=thread_id,
        payload=dict(payload),
    )
