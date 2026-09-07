"""Command-line runner for the BIST technical discovery scan.

The scan is intentionally lighter than /analiz.  It downloads market data once,
ranks discovery candidates, enriches the saved result with confirmed structure
and role-aware levels, renders research-style summary cards and creates one
concise detail card for newly surfaced top candidates.  Full company research
remains an explicit /analiz command.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.intervals import resolve
from src.market_context import market_structure, profile_context
from src.scan_card import render_scan_cards, render_scan_detail_card
from src.scan_scheduler import resolve_intervals
from src.scan_state import (
    MARKET_TIMEZONE,
    load_state,
    mark_reported,
    save_state,
    select_new,
)
from src.screener import (
    INTERVAL_ORDER,
    SCREENS,
    chunked,
    default_options,
    merge_interval_results,
    run_screen,
)
from src.stock_dashboard import calculate_indicators
from src.telegram_client import send_analyst_cards
from src.universe import load_universe
from src.watch_alerts import select_watch_levels

MAX_RETRIES = 3
BACKOFF_SECONDS = 5.0
MAX_TELEGRAM_ROWS = 25


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not all(column in frame.columns for column in required):
        return pd.DataFrame()
    clean = frame[required].dropna(subset=["Open", "High", "Low", "Close"]).copy()
    clean["Volume"] = clean["Volume"].fillna(0.0)
    return clean


def build_fetcher(period: str, interval: str, sleep: float = BACKOFF_SECONDS):
    """Return a batched borsapy downloader with bounded backoff."""
    import borsapy as bp

    def fetch(batch: list[str]) -> dict[str, pd.DataFrame]:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                raw = bp.download(batch, period=period, interval=interval, group_by="ticker", progress=False)
                break
            except Exception as error:
                last_error = error
                if attempt == MAX_RETRIES - 1:
                    raise
                time.sleep(sleep * (attempt + 1))
        else:  # pragma: no cover
            raise last_error or RuntimeError("indirme başarısız")

        frames: dict[str, pd.DataFrame] = {}
        for ticker in batch:
            try:
                frame = raw[ticker] if isinstance(raw.columns, pd.MultiIndex) else raw
            except KeyError:
                continue
            normalized = _normalize(frame)
            if not normalized.empty:
                frames[ticker] = normalized
        return frames

    return fetch


def _result_line(item: dict[str, Any], labels: dict[str, str]) -> list[str]:
    """Plain-text fallback for logs and non-image consumers."""
    setup = str(item.get("setup", ""))
    tags = [labels.get(name, name) for name in item.get("screens", [])]
    tags = [tag for tag in tags if tag.casefold() != setup.casefold()]
    excess = item.get("excess_return_20")
    rs = ""
    if isinstance(excess, (int, float)) and math.isfinite(float(excess)):
        rs = f" | XU100 {excess:+.1f} puan"
    head = (
        f"• {item['ticker']} {item['close']:.2f} | RVOL {item['rvol']:.2f}x | "
        f"BB %{item['bb_width_percentile']:.0f}{rs}"
    )
    detail = setup or ""
    if tags:
        detail = f"{detail} — {', '.join(tags)}" if detail else ", ".join(tags)
    lines = [head, f"   {detail}"]
    active = item.get("active_levels") or {}
    try:
        lower = float(active["lower"])
        reference = float(active["reference_close"])
        upper = float(active["upper"])
    except (KeyError, TypeError, ValueError):
        lower = reference = upper = math.nan
    if math.isfinite(lower) and lower < reference < upper:
        lines.append(f"   Yapı: {lower:.2f} < ref {reference:.2f} < {upper:.2f}")
    for note in item.get("notes", [])[:1]:
        lines.append(f"   ⚠ {note}")
    return lines


def _error_lines(payload: dict[str, Any]) -> list[str]:
    kinds = payload.get("error_kinds", {})
    if not kinds:
        return []
    lines = [""]
    short = kinds.get("kisa_gecmis", [])
    missing = kinds.get("veri_yok", [])
    broken = kinds.get("ariza", [])
    if short or missing:
        lines.append(
            f"ℹ Taranamayan {len(short) + len(missing)} sembol: yetersiz geçmiş veya veri yok "
            "(yeni halka arz, fon, varant)."
        )
    if broken:
        sample = ", ".join(broken[:6])
        lines.append(f"⚠ Gerçek hata veren {len(broken)} sembol: {sample}")
        if len(broken) > 6:
            lines.append("   (tam liste JSON çıktısında)")
    return lines


def summary_text(payload: dict[str, Any], universe_source: str, elapsed: float) -> str:
    """Text counterpart of the scan summary; kept for diagnostics."""
    results = payload.get("results", [])[:MAX_TELEGRAM_ROWS]
    broken = len(payload.get("error_kinds", {}).get("ariza", []))
    lines = [
        "🔎 BIST Teknik Tarama",
        f"Evren: {payload.get('requested', 0)} sembol ({universe_source})",
        (
            f"İşlenen: {payload.get('processed', 0)} | Eşleşen: {payload.get('matched', 0)} | "
            f"Likidite: {payload.get('illiquid', 0)} | Koşul dışı: {payload.get('no_match', 0)} | Arıza: {broken}"
        ),
        f"Süre: {elapsed / 60:.1f} dk",
        "",
    ]
    if results:
        labels = {name: SCREENS[name]["label"] for name in SCREENS}
        for item in results:
            lines.extend(_result_line(item, labels))
        if payload.get("matched", 0) > len(results):
            lines.append(f"… ve {payload['matched'] - len(results)} sembol daha (tam liste JSON çıktısında).")
    else:
        lines.append("Bu taramada koşulları karşılayan sembol bulunamadı.")
    lines.extend(_error_lines(payload))
    lines.extend(["", "Durum taramasıdır; AL/SAT sinyali veya yatırım tavsiyesi değildir."])
    return "\n".join(lines)


def fetch_benchmark(symbol: str, period: str, interval: str) -> pd.Series | None:
    """Download the relative-strength benchmark once; failure is non-fatal."""
    if not symbol:
        return None
    try:
        import borsapy as bp

        frame = bp.Index(symbol.removesuffix(".IS")).history(period=period, interval=interval)
        clean = _normalize(frame)
        return clean["Close"] if not clean.empty else None
    except Exception:  # noqa: BLE001
        return None


def _profile_summary(profile: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "poc",
        "vah",
        "val",
        "position",
        "acceptance",
        "developing_acceptance",
        "poc_migration",
        "value_area_state",
    )
    return {key: profile.get(key) for key in keys if profile.get(key) is not None}


def _enrich_one_interval(frame: pd.DataFrame, interval: str) -> dict[str, Any]:
    """Build scan-safe structure context without refetching market data."""
    data = calculate_indicators(frame, interval)
    structure = market_structure(data)
    profile = profile_context(data)
    try:
        active_levels = select_watch_levels(data, "BIST", interval)
    except ValueError:
        active_levels = {}
    return {
        "structure": structure,
        "profile": _profile_summary(profile),
        "active_levels": active_levels,
    }


def enrich_scan_results(
    payload: dict[str, Any],
    scan_frames: dict[str, dict[str, pd.DataFrame]],
) -> dict[str, Any]:
    """Attach confirmed structure, profile and role-aware levels to each result.

    The saved JSON then powers /liste and /gecmis with the same semantics as the
    live scan card.  A raw swing on the wrong side of price is never promoted to
    an active support/resistance threshold.
    """
    for item in payload.get("results", []):
        ticker = str(item.get("ticker", ""))
        frames = scan_frames.get(ticker, {})
        if not frames:
            continue
        contexts: dict[str, dict[str, Any]] = {}
        for interval, frame in frames.items():
            try:
                contexts[interval] = _enrich_one_interval(frame, interval)
            except Exception as error:  # noqa: BLE001 - enrichment must not kill the full scan
                item.setdefault("notes", []).append(
                    f"{interval} yapı zenginleştirmesi yapılamadı ({type(error).__name__})"
                )
        if not contexts:
            continue

        existing = item.get("intervals")
        if isinstance(existing, dict):
            for interval, context in contexts.items():
                existing.setdefault(interval, {}).update(context)
        elif len(contexts) > 1:
            item["intervals"] = contexts

        preferred = min(contexts, key=lambda key: INTERVAL_ORDER.get(key, 99))
        item["structure"] = contexts[preferred]["structure"]
        item["profile"] = contexts[preferred]["profile"]
        item["active_levels"] = contexts[preferred]["active_levels"]
    return payload


def build_scan_candidate_report(
    item: dict[str, Any],
    prices: pd.DataFrame,
    directory: Path,
    interval: str,
) -> list[Path]:
    """Render one concise candidate card from the already-scanned frame."""
    ticker = str(item["ticker"])
    target = directory / ticker
    target.mkdir(parents=True, exist_ok=True)
    path = render_scan_detail_card(item, prices, target / f"{ticker}_tarama_adayi.png", interval)
    return [path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BIST geneli teknik durum taraması yapar.")
    parser.add_argument("--universe", default="auto", choices=["auto", "provider", "file"], help="Sembol kaynağı")
    parser.add_argument("--watchlist", default="watchlist.txt", help="Yerel sembol listesi (yedek kaynak)")
    parser.add_argument("--limit", type=int, default=0, help="En fazla kaç sembol taransın (0 = sınırsız)")
    parser.add_argument("--period", default="", help="Boşsa mum aralığının varsayılan dönemi kullanılır")
    parser.add_argument("--interval", default="auto", help="'auto', tek aralık veya virgülle birden fazla (ör. 1h,4h)")
    parser.add_argument("--batch-size", type=int, default=40)
    parser.add_argument("--screens", default="", help="Virgülle ayrılmış tarama adları; boşsa hepsi")
    parser.add_argument("--bb-rank-max", type=float, default=default_options()["bb_rank_max"])
    parser.add_argument("--rvol-min", type=float, default=default_options()["rvol_min"])
    parser.add_argument("--rvol-spike", type=float, default=default_options()["rvol_spike"])
    parser.add_argument("--min-turnover", type=float, default=default_options()["min_turnover"])
    parser.add_argument("--benchmark", default="XU100", help="Göreceli güç endeksi (boş = kapalı)")
    parser.add_argument("--output", default="reports/screener.json")
    parser.add_argument(
        "--report-top",
        type=int,
        default=3,
        help="Kaç yeni eşleşme için araştırma-dili tarama aday kartı üretilsin (0 = kapalı)",
    )
    parser.add_argument("--report-detail", default="kompakt", choices=["kompakt", "dengeli", "tam"])
    parser.add_argument("--state", default="reports/scan_state.json", help="Gün içi tekrar önleme durumu")
    parser.add_argument("--title", default="BIST Teknik Tarama")
    parser.add_argument("--send-telegram", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    universe = load_universe(args.universe, Path(args.watchlist))
    symbols = universe.symbols[: args.limit] if args.limit > 0 else universe.symbols
    print(f"Evren: {len(symbols)} sembol ({universe.source}) | aralık(lar): {args.interval}")

    enabled = [name.strip() for name in args.screens.split(",") if name.strip()] or list(SCREENS)
    options = {
        "bb_rank_max": args.bb_rank_max,
        "rvol_min": args.rvol_min,
        "rvol_spike": args.rvol_spike,
        "min_turnover": args.min_turnover,
    }
    selection = resolve_intervals(args.interval)
    intervals = [item.strip() for item in selection.split(",") if item.strip()]
    if not intervals:
        raise SystemExit(f"Geçersiz aralık değeri: {args.interval!r}")

    started = time.perf_counter()
    payloads: dict[str, dict[str, Any]] = {}
    scan_frames: dict[str, dict[str, pd.DataFrame]] = {}
    for interval in intervals:
        interval_period = args.period or resolve(interval).default_period
        benchmark = fetch_benchmark(args.benchmark, interval_period, interval)
        if benchmark is None and args.benchmark:
            print(f"Uyarı: {args.benchmark} verisi alınamadı ({interval}); göreceli güç hesaplanmayacak.")
        print(f"  {interval} taraması başlıyor (dönem {interval_period})…")
        result = run_screen(
            symbols,
            build_fetcher(interval_period, interval),
            options=options,
            enabled=enabled,
            interval=interval,
            batch_size=args.batch_size,
            benchmark=benchmark,
            keep_frames=True,
        )
        for ticker, frame in result.pop("frames", {}).items():
            scan_frames.setdefault(ticker, {})[interval] = frame
        payloads[interval] = result
        print(f"  {interval}: {result['matched']} eşleşme, {result['processed']} işlendi.")

    payload = merge_interval_results(payloads) if len(payloads) > 1 else payloads[intervals[0]]
    payload.pop("frames", None)
    elapsed = time.perf_counter() - started
    payload["universe_source"] = universe.source
    payload["elapsed_seconds"] = round(elapsed, 1)
    payload["batches"] = len(chunked(symbols, args.batch_size))
    payload["options"] = options
    payload["screens"] = enabled
    payload["interval"] = intervals[0]
    if len(intervals) > 1:
        payload["intervals"] = intervals

    payload = enrich_scan_results(payload, scan_frames)

    stamp = datetime.now(MARKET_TIMEZONE).strftime("%d.%m.%Y %H:%M")
    payload["timestamp"] = stamp
    label = " + ".join(intervals)
    payload["header_line"] = f"{stamp} · {label} tarama"

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(
        f"Tarama bitti: {payload['processed']} işlendi, {payload['matched']} eşleşme, "
        f"{len(payload['errors'])} hata, {elapsed / 60:.1f} dk."
    )
    print(f"JSON: {output}")

    reports_dir = output.parent
    scan_cards = render_scan_cards(payload, reports_dir, universe.source, elapsed, title=args.title)
    print(f"{len(scan_cards)} araştırma-dili tarama kartı üretildi.")

    state_path = Path(args.state)
    reported = load_state(state_path)
    fresh = select_new(payload.get("results", []), reported, args.report_top)
    symbol_images: list[Path] = []
    produced: list[dict[str, Any]] = []
    for item in fresh:
        ticker = str(item["ticker"])
        try:
            frames = scan_frames.get(ticker, {})
            if not frames:
                print(f"  {ticker}: aday kartı için veri bulunamadı, atlanıyor.")
                continue
            report_interval = min(frames, key=lambda key: INTERVAL_ORDER.get(key, 99))
            images = build_scan_candidate_report(item, frames[report_interval], reports_dir, report_interval)
            symbol_images.extend(images)
            produced.append(item)
            print(f"  {ticker}: {len(images)} tarama aday kartı üretildi.")
        except Exception as error:  # noqa: BLE001
            print(f"  {ticker}: aday kartı üretilemedi ({type(error).__name__}: {error}).")
    if produced:
        save_state(mark_reported(produced, reported), state_path)

    if args.send_telegram:
        send_analyst_cards(scan_cards, {})
        if symbol_images:
            send_analyst_cards(symbol_images, {})
        print(f"Telegram'a {len(scan_cards) + len(symbol_images)} görsel gönderildi.")
    else:
        print(f"Üretilen görsel: {len(scan_cards) + len(symbol_images)} (gönderim kapalı).")


if __name__ == "__main__":
    main()
