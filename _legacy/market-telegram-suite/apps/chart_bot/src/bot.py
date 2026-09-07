"""Telegram grafik botu.

/grafik artık eski 2x2 eşit gösterge ızgarasını üretmez. Her zaman aralığı için
tek, beyaz temalı teknik dashboard üretir: büyük fiyat/trend alanı ile MACD,
SMI, RSI, OBV, ATR, RVOL ve ADX/DMI yardımcı panelleri aynı sayfadadır.

Çalışma biçimleri:

    python -m src.bot                 süresiz dinler (Ctrl+C ile durur)
    python -m src.bot --minutes 50    50 dakika dinler, sonra çıkar
    python -m src.bot --once          bekleyenleri işler ve çıkar

--minutes GitHub Actions için tek koşu boyunca sürekli dinleme sağlar; süre
dolunca bot_runner kendini yeniden tetikleyip zinciri sürdürür. Sık cron'lara
güvenmek yerine bu yöntem tercih edilir çünkü kısa aralıklı Actions cron'ları
pratikte gecikebilir veya atlanabilir ve komutlar cevapsız kalabilir.

Offset (işlenen son Telegram güncellemesi) diske yazılır. Böylece Actions
koşuları arasında komut kaybolmaz ve aynı komut iki kez işlenmez.

Komutlar:
    /grafik TMPOL                 varsayılan aralıklar (4h, 1d, 1wk, 1mo)
    /grafik TMPOL 1d              tek aralık
    /grafik ASELS 4h,1d           birden fazla aralık
    /grafik BTC-USD 1d            kripto ve yabancı hisse de çalışır
    /grafikyardim                 komut yardımı

Bot yalnız TELEGRAM_CHAT_ID ve (tanımlıysa) TELEGRAM_TOPIC_ID ile eşleşen
sohbet/konudaki komutları işler. Böylece aynı gruptaki teknik/araştırma botuyla
konu ayrımı korunur.

Bot uzun yoklama (long polling) kullanır; açık port veya webhook gerektirmez.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path

from . import telegram as tg
from .pipeline import INTERVAL_LABELS
from .technical_dashboard import build_technical_dashboard

DEFAULT_INTERVALS = ("4h", "1d", "1wk", "1mo")
LONG_POLL_SECONDS = 25
STATE_FILE = Path(os.environ.get("BOT_STATE_FILE", "state/telegram_offset.json"))
BUSY_MESSAGE = "Şu anda başka bir grafik hazırlanıyor, birazdan tekrar deneyin."


def load_offset() -> int | None:
    try:
        return int(json.loads(STATE_FILE.read_text(encoding="utf-8"))["offset"])
    except Exception:  # noqa: BLE001
        return None


def save_offset(offset: int) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"offset": offset}), encoding="utf-8")
    except OSError as exc:
        print(f"offset yazılamadı: {exc}")


# /kareler kaldırıldı: eski dört eşit karo düzeni artık kullanıcıya sunulmuyor.
OWN_COMMANDS = {"grafik", "grafikyardim"}
SHARED_COMMANDS = {"yardim", "help", "start"}


def _allowed(message: dict) -> bool:
    expected = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not expected or str(message.get("chat", {}).get("id")) != expected:
        return False

    topic = os.environ.get("TELEGRAM_TOPIC_ID", "").strip()
    if not topic:
        return True
    thread = message.get("message_thread_id")
    return thread is not None and str(thread) == topic


def _parse(text: str, username: str = "") -> tuple[str, list[str]]:
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return "", []

    head = parts[0][1:]
    command, _, target = head.partition("@")
    command, target = command.lower(), target.lower()

    if target:
        if username and target != username:
            return "", []
    elif command in SHARED_COMMANDS:
        return "", []

    return command, parts[1:]


def _render_and_send(symbol: str, intervals: list[str], thread_id: str | None) -> None:
    outdir = Path(os.environ.get("BOT_OUTDIR", "out"))
    sent = 0
    for interval in intervals:
        try:
            result = build_technical_dashboard(symbol, interval=interval, outdir=outdir)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            tg.send_message(f"⚠️ <b>{symbol}</b> · {interval}: {exc}", thread_id)
            continue

        label = INTERVAL_LABELS.get(interval, interval)
        caption = tg.build_caption(
            f"{result.symbol} · {label}",
            result.subtitle,
            result.snapshot,
        )
        # Yüksek çözünürlüklü dashboard belge olarak gönderilir; Telegram'ın
        # fotoğraf küçültmesi panel yazılarını bozmasın.
        tg.send_document(result.path, caption, thread_id)
        sent += 1

    if sent == 0:
        tg.send_message(f"❌ <b>{symbol}</b> için grafik üretilemedi.", thread_id)


def _help(thread_id: str | None) -> None:
    tg.send_message(
        "<b>Grafik Botu</b>\n"
        "/grafik SEMBOL [aralık] — teknik dashboard üretir\n"
        "   örn: <code>/grafik TMPOL</code>\n"
        "   örn: <code>/grafik ASELS 1d</code>\n"
        "   örn: <code>/grafik BTC-USD 4h,1d</code>\n"
        f"   varsayılan: {', '.join(DEFAULT_INTERVALS)}\n\n"
        "Dashboard: mum + Bollinger + AlphaTrend + EMA8/21/55 + "
        "HH/HL/LH/LL/BOS + hacim; MACD/SMI; RSI/OBV; ATR/RVOL/ADX-DMI.\n"
        "Otomatik AL/SAT etiketi içermez.\n\n"
        "/grafikyardim — bu mesaj",
        thread_id,
    )


def handle(message: dict) -> None:
    text = message.get("text", "")
    thread_id = message.get("message_thread_id")
    thread_id = str(thread_id) if thread_id is not None else None
    command, args = _parse(text, tg.get_me())

    if command in SHARED_COMMANDS | {"grafikyardim"}:
        _help(thread_id)
        return

    if command != "grafik":
        return

    if not args:
        tg.send_message("Sembol gerekli. Örnek: <code>/grafik TMPOL</code>", thread_id)
        return

    symbol = args[0].upper()
    if len(args) > 1:
        intervals = [i for i in args[1].replace(",", " ").split() if i]
        unknown = [i for i in intervals if i not in INTERVAL_LABELS]
        if unknown:
            tg.send_message(
                f"Bilinmeyen aralık: {', '.join(unknown)}\n"
                f"Geçerli: {', '.join(INTERVAL_LABELS)}",
                thread_id,
            )
            return
    else:
        intervals = list(DEFAULT_INTERVALS)

    tg.send_message(
        f"⏳ <b>{symbol}</b> teknik dashboard hazırlanıyor · {', '.join(intervals)}",
        thread_id,
    )
    _render_and_send(symbol, intervals, thread_id)


def poll_once(timeout: int = 0) -> int:
    tg._credentials()
    updates = tg.get_updates(offset=load_offset(), timeout=timeout)
    if not updates:
        return 0

    handled = 0
    last_id = updates[-1]["update_id"]
    save_offset(last_id + 1)
    for update in updates:
        message = update.get("message")
        if not message or not _allowed(message):
            continue
        try:
            handle(message)
            handled += 1
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    tg.get_updates(offset=last_id + 1, timeout=0)
    return handled


def run(minutes: float | None = None, poll_timeout: int = LONG_POLL_SECONDS) -> int:
    tg._credentials()
    offset = load_offset()
    deadline = time.monotonic() + minutes * 60 if minutes else None

    print("Bot dinliyor. Komutlar: /grafik SEMBOL [aralık] · /grafikyardim")
    if deadline:
        print(f"Çalışma süresi: {minutes:.0f} dakika")

    handled = 0
    while deadline is None or time.monotonic() < deadline:
        try:
            updates = tg.get_updates(offset=offset, timeout=poll_timeout)
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # noqa: BLE001
            print(f"getUpdates hatası: {exc}")
            time.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            save_offset(offset)
            message = update.get("message")
            if not message or not _allowed(message):
                continue
            try:
                handle(message)
                handled += 1
            except Exception:  # noqa: BLE001
                traceback.print_exc()
                try:
                    tg.send_message(
                        "❌ Beklenmeyen hata; günlüğe yazıldı.",
                        str(message.get("message_thread_id") or "") or None,
                    )
                except Exception:  # noqa: BLE001
                    pass
    return handled


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="market-chart-lab bot")
    parser.add_argument("--once", action="store_true", help="Bekleyen komutları işle ve çık")
    parser.add_argument("--minutes", type=float, default=None, help="Kaç dakika dinlensin (boş: süresiz)")
    options = parser.parse_args()

    if options.once:
        print(f"{poll_once()} komut işlendi")
    else:
        try:
            print(f"{run(minutes=options.minutes)} komut işlendi")
        except KeyboardInterrupt:
            print("\nBot durduruldu.")
