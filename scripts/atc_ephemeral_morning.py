"""Publish a real previous-session 630-share morning pivot report.

Fetch confirmed vendor bars only. No Neon database writes or fabricated levels.
"""
from __future__ import annotations

import argparse
import base64
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.delivery.telegram.http_transport import HttpxTelegramTransport
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.providers import FetchRequest
from market_intelligence.scheduling.xist import ExchangeCalendarsXist
from scripts.atc_telegram_briefings import last_closed_session, morning_messages, pivot_levels
from scripts.atc_universe_seed import load_pinned

IST = ZoneInfo("Europe/Istanbul")


def read_last_close(symbol, *, day, now, provider=None):
    frame = (provider or BorsapyProvider()).fetch(FetchRequest(
        provider_symbol=symbol, timeframe=Timeframe.D1, bars=8, as_of=now,
    ))
    candles = [
        bar for bar in frame.bars
        if (bar.timestamp.replace(tzinfo=IST) if bar.timestamp.tzinfo is None
            else bar.timestamp.astimezone(IST)).date() == day
    ]
    if len(candles) != 1:
        return (symbol, None, None, "VERI_YOK")
    bar = candles[0]
    try:
        levels = pivot_levels(bar.high, bar.low, bar.close)
        if bar.volume < 0:
            raise ValueError("negative volume")
    except ValueError:
        return (symbol, None, None, "VERI_HATASI")
    return (symbol, levels, bar.close * bar.volume, "TEYITLI")


def gather_morning(*, now, symbols, workers=6):
    current = now.astimezone(IST).date()
    calendar = ExchangeCalendarsXist()
    if current not in calendar.sessions(current, current):
        raise ValueError("No BIST session today")
    previous = last_closed_session(calendar, current)

    def check(symbol):
        try:
            return read_last_close(symbol, day=previous, now=now)
        except (RuntimeError, ValueError, KeyError, TypeError):
            return symbol, None, None, "VERI_YOK"

    with ThreadPoolExecutor(max_workers=workers) as executor:
        rows = list(executor.map(check, symbols))
    return previous, rows


def publish_morning(*, now=None, workers=6):
    now = now or datetime.now(IST)
    symbols = load_pinned(Path("config/atc_630_symbols.txt"))
    previous, rows = gather_morning(now=now, symbols=symbols, workers=workers)
    message, csv_bytes = morning_messages(previous, rows)
    chat = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
    thread = int(os.environ.get("TELEGRAM_TOPIC_REPORTS", "0"))
    if chat != -1004439315048 or thread != 8:
        raise ValueError("Expected original ATC Reports topic")
    sender = HttpxTelegramTransport(os.environ["TELEGRAM_BOT_TOKEN"])
    text_id = sender.send(chat_id=chat, message_thread_id=thread, payload={"text": message})
    print(f"Morning text: https://t.me/c/4439315048/8/{text_id}", flush=True)
    file_id = sender.send(chat_id=chat, message_thread_id=thread, payload={
        "_method": "sendDocument",
        "document_base64": base64.b64encode(csv_bytes).decode("ascii"),
        "filename": f"ATC_630_PIVOT_{previous}.csv",
        "caption": f"ATC 630 | {previous} confirmed daily OHLCV pivots | YTD",
    })
    print(f"Morning full CSV: https://t.me/c/4439315048/8/{file_id}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    if not 1 <= args.workers <= 10:
        parser.error("workers must be 1-10")
    publish_morning(workers=args.workers)


if __name__ == "__main__":
    main()
