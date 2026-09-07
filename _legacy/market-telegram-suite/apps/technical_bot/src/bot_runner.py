"""Telegram bot çalıştırıcısı.

Kısa komutları doğrudan işler; uzun taramalar aktif GitHub Actions akışına
delege edilir. Takip uyarıları yalnızca teyit edilmiş mum kapanışlarında ve
referans fiyatın iki yanına doğrulanmış yapısal seviyelerde çalışır.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

import requests

from src.analyst_card import standardize_pages
from src.bot_settings import (
    apply_change,
    defaults,
    load_settings,
    save_settings,
    workflow_inputs,
)
from src.bot_settings import describe as describe_settings
from src.intervals import INTERVALS, resolve
from src.scan_card import render_scan_cards
from src.scan_scheduler import (
    SLOTS,
    due_slot,
    load_state,
    mark_done,
    now_market,
    save_state,
)
from src.stock_dashboard import (
    ScanConfig,
    build_status,
    calculate_indicators,
    download_prices,
)
from src.telegram_bot import (
    HELP_TEXT,
    fetch_updates,
    is_authorized,
    load_offset,
    parse_command,
    save_offset,
    validate_report_args,
    validate_scan_args,
)
from src.telegram_client import send_analyst_cards, send_text
from src.watch_alerts import (
    Watch,
    add_watch,
    check_break,
    latest_confirmed_close,
    load_watches,
    remove_watch,
    save_watches,
    select_watch_levels,
)
from src.watch_alerts import describe as describe_watches

REPORTS_DIR = Path("reports")
SCREENER_JSON = REPORTS_DIR / "screener.json"
MAX_COMMANDS_PER_RUN = 5
DISPATCH_RETRY_SECONDS = 300.0
WATCH_CHECK_SECONDS = 600.0
BOT_WORKFLOW_FILE = os.getenv("BOT_WORKFLOW_FILE", "technical-bot.yml")
SCAN_WORKFLOW_FILE = os.getenv("SCAN_WORKFLOW_FILE", "technical-scan.yml")
SCAN_ARTIFACT_PREFIXES = ("bist-tarama", "bist-teknik-tarama")
_last_dispatch_attempt = 0.0
_last_watch_check = 0.0


def reply(chat_id: int, text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    thread = os.getenv("TELEGRAM_MESSAGE_THREAD_ID", "").strip()
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if thread:
        payload["message_thread_id"] = int(thread)
    requests.post(f"https://api.telegram.org/bot{token}/sendMessage", data=payload, timeout=30)


def dispatch_scan(intervals: str) -> tuple[bool, str]:
    """Uzun süren taramayı aktif scan workflow'una delege eder."""
    token = os.getenv("GITHUB_TOKEN", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    if not token or not repository:
        return False, "Tarama tetiklenemedi: GitHub kimlik bilgisi yok."
    response = requests.post(
        f"https://api.github.com/repos/{repository}/actions/workflows/{SCAN_WORKFLOW_FILE}/dispatches",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        json={
            "ref": os.getenv("GITHUB_REF_NAME", "main"),
            "inputs": {"interval": intervals, "universe": "auto", "limit": "0", **workflow_inputs(load_settings())},
        },
        timeout=30,
    )
    if response.status_code == 204:
        return True, f"Tarama başlatıldı ({intervals}). Sonuç 25-30 dakika içinde bu gruba düşecek."
    return False, f"Tarama tetiklenemedi: HTTP {response.status_code} — {response.text[:150]}"


def list_scan_artifacts(limit: int = 10) -> list[dict[str, Any]]:
    """Aktif ve eski adlandırmadaki tarama artifact'lerini, yeniden eskiye listeler."""
    token = os.getenv("GITHUB_TOKEN", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    if not token or not repository:
        return []
    response = requests.get(
        f"https://api.github.com/repos/{repository}/actions/artifacts",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        params={"per_page": 100},
        timeout=30,
    )
    if not response.ok:
        return []
    artifacts = [
        item
        for item in response.json().get("artifacts", [])
        if any(str(item.get("name", "")).startswith(prefix) for prefix in SCAN_ARTIFACT_PREFIXES)
        and not item.get("expired")
    ]
    artifacts.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return artifacts[:limit]


def download_scan_json(artifact: dict[str, Any]) -> dict[str, Any] | None:
    """Artifact zip'ini indirip içindeki screener.json dosyasını okur."""
    import io
    import zipfile

    token = os.getenv("GITHUB_TOKEN", "")
    response = requests.get(
        str(artifact.get("archive_download_url", "")),
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    )
    if not response.ok:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            name = next((item for item in archive.namelist() if item.endswith("screener.json")), "")
            if not name:
                return None
            return json.loads(archive.read(name).decode("utf-8"))
    except (zipfile.BadZipFile, ValueError, KeyError):
        return None


def _latest_scan_payload() -> dict[str, Any] | None:
    artifacts = list_scan_artifacts(limit=1)
    if artifacts:
        payload = download_scan_json(artifacts[0])
        if payload:
            return payload
    try:
        return json.loads(SCREENER_JSON.read_text(encoding="utf-8"))
    except (OSError, ValueError, AttributeError):
        return None


def handle_list(chat_id: int) -> None:
    payload = _latest_scan_payload()
    if not payload:
        reply(chat_id, "Henüz kayıtlı bir tarama sonucu yok. /tara ile yeni tarama başlatabilirsiniz.")
        return
    if not payload.get("results"):
        reply(chat_id, "Son taramada eşleşme yok.")
        return
    cards = render_scan_cards(
        payload,
        REPORTS_DIR / "komut",
        payload.get("universe_source", "borsapy"),
        float(payload.get("elapsed_seconds", 0.0)),
        title="Son Tarama — Tam Liste",
        limit=60,
        stem="liste_card",
    )
    standardize_pages(cards)
    send_analyst_cards(cards, {})


def handle_settings(chat_id: int, args: list[str]) -> None:
    values = load_settings()
    if not args:
        reply(chat_id, describe_settings(values))
        return
    if args[0].strip().casefold() in {"sifirla", "sıfırla", "reset"}:
        save_settings(defaults())
        reply(chat_id, "Eşikler varsayılana döndürüldü.\n\n" + describe_settings(defaults()))
        return
    if len(args) < 2:
        reply(chat_id, "Kullanım: /esik rvol 2.0")
        return
    updated, message = apply_change(values, args[0], args[1])
    if updated is None:
        reply(chat_id, message)
        return
    save_settings(updated)
    reply(chat_id, message + "\n\nSonraki taramadan itibaren geçerli.")


def _watch_from_levels(ticker: str, interval: str, setup_name: str, levels: dict[str, Any]) -> Watch:
    return Watch(
        ticker=ticker,
        interval=interval,
        upper=float(levels["upper"]),
        lower=float(levels["lower"]),
        setup=setup_name,
        added_at=now_market().isoformat(timespec="minutes"),
        reference_close=float(levels["reference_close"]),
        lower_source=str(levels["lower_source"]),
        upper_source=str(levels["upper_source"]),
        reference_bar=str(levels["reference_bar"]),
        last_checked_bar=str(levels["reference_bar"]),
    )


def handle_watch(chat_id: int, args: list[str], intervals: set[str]) -> None:
    watches = load_watches()
    if not args:
        reply(chat_id, describe_watches(watches))
        return
    if args[0].strip().casefold() in {"sil", "cikar", "çıkar", "remove"}:
        if len(args) < 2:
            reply(chat_id, "Kullanım: /takip sil THYAO")
            return
        updated, message = remove_watch(watches, args[1])
        if updated is not None:
            save_watches(updated)
        reply(chat_id, message)
        return

    ticker, interval, error = validate_report_args(args, intervals, command="takip")
    if error:
        reply(chat_id, error)
        return
    reply(chat_id, f"{ticker} için teyitli yapı seviyeleri hesaplanıyor…")
    config = ScanConfig(ticker=ticker, market="BIST", interval=interval)
    symbol, prices = download_prices(config)
    data = calculate_indicators(prices, interval)
    status = build_status(data, config, symbol)
    setup = status.get("technical_commentary", {}).get("setup", {})
    try:
        levels = select_watch_levels(data, "BIST", interval, now=now_market())
    except ValueError as error:
        reply(chat_id, f"{ticker} takibe alınamadı: {error}")
        return

    watch = _watch_from_levels(ticker, interval, str(setup.get("name", "")), levels)
    updated, message = add_watch(watches, watch)
    if updated is not None:
        save_watches(updated)
    reply(chat_id, message)


def handle_status(chat_id: int) -> None:
    values = load_settings()
    watches = load_watches()
    state = load_state()
    current = now_market()
    done = ", ".join(sorted(key for key, day in state.items() if day == current.date().isoformat())) or "yok"
    upcoming = next((slot for slot in SLOTS if (slot.hour, slot.minute) > (current.hour, current.minute)), None)
    lines = [
        "🤖 Bot durumu",
        f"Saat: {current.strftime('%d.%m.%Y %H:%M')} (Türkiye)",
        f"Bugün çalışan tarama slotları: {done}",
        f"Sıradaki slot: {upcoming.key + ' (' + upcoming.intervals + ')' if upcoming else 'bugünlük tamamlandı'}",
        f"Takip edilen sembol: {len(watches)}",
        "",
        describe_settings(values),
    ]
    reply(chat_id, "\n".join(lines))


def handle_history(chat_id: int, args: list[str]) -> None:
    artifacts = list_scan_artifacts()
    if not artifacts:
        reply(chat_id, "Geçmiş tarama bulunamadı. Artifact'ler 30 gün saklanır.")
        return
    if not args:
        lines = ["Kayıtlı taramalar (numarayla çağırın, ör. /gecmis 2):"]
        for index, item in enumerate(artifacts, start=1):
            stamp = str(item.get("created_at", ""))[:16].replace("T", " ")
            lines.append(f"{index}. {stamp} — {item.get('name', '')}")
        reply(chat_id, "\n".join(lines))
        return
    try:
        choice = int(args[0])
    except ValueError:
        reply(chat_id, "Kullanım: /gecmis 2")
        return
    if not 1 <= choice <= len(artifacts):
        reply(chat_id, f"1 ile {len(artifacts)} arasında bir numara verin.")
        return
    artifact = artifacts[choice - 1]
    reply(chat_id, f"{str(artifact.get('created_at', ''))[:16].replace('T', ' ')} taraması getiriliyor…")
    payload = download_scan_json(artifact)
    if not payload:
        reply(chat_id, "Tarama sonucu okunamadı.")
        return
    cards = render_scan_cards(
        payload,
        REPORTS_DIR / "komut",
        payload.get("universe_source", "borsapy"),
        float(payload.get("elapsed_seconds", 0.0)),
        title="Geçmiş Tarama",
        limit=40,
        stem="gecmis_card",
    )
    standardize_pages(cards)
    send_analyst_cards(cards, {})


def execute(command: Any, intervals: set[str]) -> None:
    chat_id = command.chat_id
    if command.name in {"yardim", "yardım", "help", "start"}:
        reply(chat_id, HELP_TEXT)
        return
    if command.name in {"tara", "tarama"}:
        selection, error = validate_scan_args(command.args, intervals)
        if error:
            reply(chat_id, error)
            return
        _, message = dispatch_scan(selection)
        reply(chat_id, message)
        return
    if command.name in {"liste", "list"}:
        handle_list(chat_id)
        return
    if command.name in {"esik", "eşik"}:
        handle_settings(chat_id, command.args)
        return
    if command.name in {"takip", "izle"}:
        handle_watch(chat_id, command.args, intervals)
        return
    if command.name in {"durum", "status"}:
        handle_status(chat_id)
        return
    if command.name in {"gecmis", "geçmiş", "history"}:
        handle_history(chat_id, command.args)
        return
    reply(chat_id, f"Bilinmeyen komut: /{command.name}\n\n{HELP_TEXT}")


def check_schedule() -> None:
    if os.getenv("BOT_DRIVES_SCAN", "1").strip().lower() not in {"1", "true", "yes", "evet"}:
        return
    global _last_dispatch_attempt
    state = load_state()
    current = now_market()
    slot = due_slot(current, state)
    if slot is None:
        return
    now = time.perf_counter()
    if now - _last_dispatch_attempt < DISPATCH_RETRY_SECONDS:
        return
    _last_dispatch_attempt = now
    print(f"Zamanlanmış tarama slotu: {slot.key} ({slot.intervals})")
    ok, message = dispatch_scan(slot.intervals)
    print(f"  {message}")
    if ok:
        save_state(mark_done(slot, current, state))


def _legacy_watch_needs_refresh(watch: Watch) -> bool:
    return not math.isfinite(watch.reference_close) or not watch.lower < watch.reference_close < watch.upper


def check_watches() -> None:
    """Takipleri yalnızca yeni oluşmuş teyitli mum kapanışında kontrol eder."""
    global _last_watch_check
    watches = load_watches()
    if not watches:
        return
    now = time.perf_counter()
    if now - _last_watch_check < WATCH_CHECK_SECONDS:
        return
    _last_watch_check = now
    current = now_market()
    if current.weekday() >= 5 or not 9 <= current.hour < 19:
        return

    changed = False
    for ticker, watch in list(watches.items()):
        try:
            config = ScanConfig(ticker=ticker, market="BIST", interval=watch.interval)
            _, prices = download_prices(config)
            close, bar_time = latest_confirmed_close(prices, "BIST", watch.interval, now=current)

            # Eski watchlist kayıtlarında referans ve kaynak bilgisi yoktu. Bunları
            # eski/çelişkili eşik üzerinden alarm üretmek yerine güvenle migrate et.
            if _legacy_watch_needs_refresh(watch):
                levels = select_watch_levels(prices, "BIST", watch.interval, now=current)
                refreshed = _watch_from_levels(ticker, watch.interval, watch.setup, levels)
                refreshed.added_at = watch.added_at
                watches[ticker] = refreshed
                changed = True
                print(f"  eski takip seviyeleri yenilendi: {ticker}")
                continue
        except Exception as error:  # noqa: BLE001 -- tek sembol kontrolü botu durdurmamalı
            print(f"  takip kontrolü başarısız {ticker}: {type(error).__name__}")
            continue

        if bar_time == watch.last_checked_bar:
            continue

        watch.last_checked_bar = bar_time
        message = check_break(watch, close)
        if message:
            send_text(message)
            watch.triggered = current.isoformat(timespec="minutes")
            print(f"  takip uyarısı gönderildi: {ticker}")
        watches[ticker] = watch
        changed = True

    if changed:
        save_watches(watches)


def process_once(token: str, allowed: set[int], long_poll: int) -> int:
    offset = load_offset()
    updates = fetch_updates(token, offset, long_poll=long_poll)
    if not updates:
        return 0
    highest = offset
    handled = 0
    for update in updates:
        highest = max(highest, int(update.get("update_id", 0)))
        command = parse_command(update)
        if command is None:
            continue
        if not is_authorized(command, allowed):
            print(f"Yetkisiz komut atlandı: /{command.name} — {command.user_name} ({command.user_id})")
            continue
        if handled >= MAX_COMMANDS_PER_RUN:
            print("Bu turda komut sınırına ulaşıldı; kalanlar sonraki turda işlenecek.")
            highest = int(update.get("update_id", 0)) - 1
            break
        print(f"Komut: /{command.name} {' '.join(command.args)} — {command.user_name}")
        started = time.perf_counter()
        try:
            execute(command, set(INTERVALS))
        except Exception as error:  # noqa: BLE001 -- tek komut botu durdurmamalı
            print(f"  hata: {type(error).__name__}: {error}")
            reply(command.chat_id, f"Komut çalıştırılamadı: {type(error).__name__}. Ayrıntı iş akışı kaydında.")
        print(f"  süre: {time.perf_counter() - started:.1f} sn")
        handled += 1
    save_offset(highest)
    return handled


def _restart_tokens() -> list[tuple[str, str]]:
    candidates = [
        (os.getenv("GITHUB_TOKEN", "").strip(), "GITHUB_TOKEN"),
        (os.getenv("GH_PAT", "").strip(), "GH_PAT"),
    ]
    result: list[tuple[str, str]] = []
    seen: set[str] = set()
    for token, source in candidates:
        if token and token not in seen:
            result.append((token, source))
            seen.add(token)
    return result


def restart_self() -> bool:
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    credentials = _restart_tokens()
    if not repository or not credentials:
        print("Kendini yeniden tetikleyemedi: GitHub kimlik bilgisi yok.")
        return False

    url = f"https://api.github.com/repos/{repository}/actions/workflows/{BOT_WORKFLOW_FILE}/dispatches"
    payload = {"ref": os.getenv("GITHUB_REF_NAME", "main").strip() or "main"}
    last_error = ""
    for token, source in credentials:
        try:
            response = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=payload,
                timeout=30,
            )
        except requests.RequestException as error:
            last_error = f"{source}: {error}"
            print(f"Dinleme zinciri isteği başarısız ({last_error}); yedek jeton deneniyor.")
            continue
        if response.status_code == 204:
            print(f"Sonraki dinleme turu tetiklendi ({source}).")
            return True
        last_error = f"{source}: HTTP {response.status_code} {response.text[:150]}"
        print(f"Dinleme zinciri isteği reddedildi ({last_error}); yedek jeton deneniyor.")

    message = "⚠ Bot dinleme zinciri devam ettirilemedi. Komutlar bir sonraki zamanlanmış koşuya kadar gecikebilir."
    print(f"{message} Son hata: {last_error}")
    try:
        send_text(message)
    except Exception as error:  # noqa: BLE001 -- bildirim hatası koşuyu bozmamalı
        print(f"  bildirim gönderilemedi: {type(error).__name__}")
    return False


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN tanımlı değil.")
    from src.telegram_bot import allowed_users

    allowed = allowed_users()
    budget = float(os.getenv("BOT_RUN_MINUTES", "50")) * 60
    long_poll = int(os.getenv("BOT_LONG_POLL_SECONDS", "25"))
    chain = os.getenv("BOT_SELF_RESTART", "1").strip().lower() in {"1", "true", "yes", "evet"}

    started = time.perf_counter()
    total = 0
    print(f"Dinleme başladı: bütçe {budget / 60:.0f} dk, uzun yoklama {long_poll} sn.")
    while time.perf_counter() - started < budget:
        try:
            check_schedule()
            check_watches()
            total += process_once(token, allowed, long_poll)
        except Exception as error:  # noqa: BLE001 -- ağ hatası dinlemeyi durdurmamalı
            print(f"Yoklama hatası: {type(error).__name__}: {error}")
            time.sleep(5)
    print(f"Dinleme bitti. Toplam {total} komut işlendi.")
    if chain:
        restart_self()


if __name__ == "__main__":
    resolve("1d")
    main()
