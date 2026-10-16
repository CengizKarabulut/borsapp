"""Publish genuine cross-timeframe intersections from verified EOD artifacts.

Each JSON result must originate from the scanner's *confirmed* completed
cycle on an isolated runner. No access to Neon or provisional market OHLCV.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.application.scan_intersections import cross_timeframe_intersections
from market_intelligence.delivery.telegram.config import TelegramSettings
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.delivery.telegram.timeframe_topics import existing_intersection_topic_id
from scripts.atc_confirmed_intersections import export_intersections_csv, make_envelopes

ISTANBUL = ZoneInfo("Europe/Istanbul")
EXPECTED = frozenset(("15m", "30m", "45m", "1h", "2h", "4h", "1d", "1wk"))


def from_verified_digests(paths, *, now, expected_timeframes=()):
    """Validate original timeframes before computing same-direction agreement."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Timezone aware now is required")
    by_tf = {}
    closes = {}
    coverage = {}
    for path in paths:
        entry = json.loads(Path(path).read_text(encoding="utf-8"))
        tf = entry.get("timeframe")
        if (entry.get("schema") != "atc-verified-timeframe-digest-v1"
                or tf not in EXPECTED or tf in by_tf
                or entry.get("universe") != 630
                or not isinstance(entry.get("entries"), list)):
            raise ValueError(f"Untrusted or duplicate scanner digest: {path}")
        covered = entry.get("covered")
        if not isinstance(covered, int) or covered < 567 or covered > 630:
            raise ValueError(f"Insufficient actual candle coverage for {tf}")
        close = datetime.fromisoformat(entry["bar_close"])
        if close.tzinfo is None or close > now + timedelta(minutes=2):
            raise ValueError(f"Invalid or future candle close for {tf}")
        max_age = timedelta(days=8 if tf == "1wk" else 2)
        if now - close > max_age:
            raise ValueError(f"Stale confirmed scanner digest for {tf}")
        details = []
        seen = set()
        for hit in entry["entries"]:
            symbol, scanner, direction = (hit["symbol"], hit["scanner"], hit["direction"])
            if (not isinstance(symbol, str) or not symbol.isascii()
                    or not symbol.isalnum() or not isinstance(scanner, str)
                    or direction not in ("bullish", "bearish")
                    or (symbol, scanner) in seen):
                raise ValueError(f"Invalid duplicate or unlabeled evidence in {tf}")
            seen.add((symbol, scanner))
            details.append({
                "symbol": symbol, "scanner": scanner, "direction": direction,
                "plan": {"scenarios": [], "price_basis": "unknown"},
            })
        by_tf[tf] = details
        closes[tf] = close
        coverage[tf] = covered
    missing = set(expected_timeframes) - set(by_tf)
    if missing:
        raise ValueError(f"Missing scanned EOD timeframe digests: {sorted(missing)}")
    if len(by_tf) < 2:
        raise ValueError("Cross-timeframe intersections require two confirmed timeframes")
    return cross_timeframe_intersections(by_tf, limit=None), closes, coverage


def publish_from_artifacts(directory, *, now=None, expected_timeframes=()):
    now = now or datetime.now(ISTANBUL)
    paths = sorted(Path(directory).glob("*.json"))
    ranked, closes, coverage = from_verified_digests(
        paths, now=now, expected_timeframes=expected_timeframes,
    )
    values = dict(os.environ)
    settings = TelegramSettings.from_mapping({**values, "DELIVERY_MODE": "live"})
    topic_id = existing_intersection_topic_id(values)
    if settings.chat_id != -1004439315048 or topic_id != 28330:
        raise ValueError("Existing verified Telegram Kesişim topic not configured")
    transport = HttpxTelegramTransport(settings.bot_token)
    messages = make_envelopes(
        settings, topic_id, ranked=ranked, closings=closes,
        coverage=coverage, now=now,
    )
    # The EOD GitHub run owns one set of daily results. No DB is needed, and
    # GitHub re-runs are independently labeled in each Telegram caption.
    sent = []
    for message in messages:
        message_id = transport.send(
            chat_id=settings.chat_id, message_thread_id=topic_id,
            payload=message.payload,
        )
        link = f"https://t.me/c/4439315048/{topic_id}/{message_id}"
        sent.append(link)
        print("ATC VERIFIED EOD Kesişim:", link, flush=True)
    print(f"EOD Kesişim: {len(ranked)} symbols, {len(closes)} timeframes, "
          f"{len(sent)} sent messages", flush=True)
    return {"timeframes": len(closes), "intersections": len(ranked), "sent": sent}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--expected", default="15m,30m,45m,1h,2h,4h,1d")
    args = parser.parse_args()
    publish_from_artifacts(
        args.directory,
        expected_timeframes=tuple(x.strip() for x in args.expected.split(",") if x.strip()),
    )


if __name__ == "__main__":
    main()
