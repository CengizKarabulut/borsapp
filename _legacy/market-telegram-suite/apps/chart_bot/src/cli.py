"""Komut satiri arayuzu.

Ornekler:
    python -m src.cli --symbol THYAO                      # 6 kare, PNG + sekmeli HTML
    python -m src.cli --symbol THYAO --views momentum     # tek kare
    python -m src.cli --symbol AAPL --interval 1h --views bollinger,momentum
    python -m src.cli --symbol BTC-USD --views all        # 7 kare (tumu dahil)
    python -m src.cli --symbol ASELS --indicators ma,rsi  # serbest liste, tek kare
    python -m src.cli --symbol GARAN --telegram           # albüm olarak gonder
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import indicators as ind
from .pipeline import (DEFAULT_PERIODS, INTERVAL_LABELS, build_chart,
                        build_views, default_bars)
from .compose import compose_grid
from .render_html import render_html
from .render_png import render_png
from .theme import get_theme
from .views import VIEWS_BY_KEY, resolve_views


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="market-chart-lab",
        description="BIST / yabanci hisse / kripto icin gostergeli fiyat grafikleri uretir.",
    )
    parser.add_argument("--symbol", "-s", required=True,
                        help="THYAO, AAPL, BTC-USD, bist:ASELS, crypto:ETH ...")
    parser.add_argument("--views", "-v", default="set",
                        help="Gorunum secimi: 'set' (8 referans kare), 'all' veya "
                             "virgullu liste: " + ", ".join(VIEWS_BY_KEY))
    parser.add_argument("--indicators", default=None,
                        help="Gorunum yerine serbest gosterge listesi (tek kare uretir). "
                             "Gecerli: " + ",".join(ind.ALL_INDICATORS))
    parser.add_argument("--interval", "-i", default="1d",
                        help="Bar araligi. Virgulle birden fazla verilebilir: "
                             "'4h,1d,1wk' -> her biri icin ayri gorsel. "
                             f"Gecerli: {', '.join(DEFAULT_PERIODS)}")
    parser.add_argument("--bars", "-b", type=int, default=None,
                        help="Grafikte gosterilecek bar sayisi. Verilmezse araliga "
                             "gore secilir (gunluk 170, haftalik 180, aylik 96).")
    parser.add_argument("--period", default=None,
                        help="Cekilecek gecmis (1mo, 1y, 5y, max). Bos ise araliga gore secilir.")
    parser.add_argument("--scale", default="auto", choices=["auto", "log", "linear"],
                        help="Fiyat ekseni. auto: aralik 4 kati asarsa log")
    parser.add_argument("--theme", default="tv", choices=["tv", "ink", "paper"])
    parser.add_argument("--grid", type=int, default=0, metavar="SUTUN",
                        help="Kareleri tek gorselde birlestir (sutun sayisi). "
                             "0 = birlestirme, kareler ayri PNG kalir.")
    parser.add_argument("--outdir", "-o", default="out", help="Cikti klasoru")
    parser.add_argument("--width", type=int, default=1600,
                        help="PNG genisligi (piksel). Tum kareler ayni genislikte uretilir.")
    parser.add_argument("--dpi", type=int, default=130)
    parser.add_argument("--project-bars", type=int, default=None,
                        help="Ichimoku bulutunu kac bar ileri tasisin (varsayilan 25)")
    parser.add_argument("--no-png", action="store_true")
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--embed-js", action="store_true",
                        help="plotly.js'i HTML icine gom (cevrimdisi acilir, ~3 MB)")
    parser.add_argument("--telegram", action="store_true",
                        help="PNG'leri albüm, HTML'i dosya olarak Telegram'a gonder")
    return parser.parse_args(argv)


def _scale(value: str) -> bool | None:
    """'auto' -> None (veriye gore karar), 'log' -> True, 'linear' -> False."""
    return {"auto": None, "log": True, "linear": False}[value]


def resolve_keys(raw: str) -> tuple[str, ...]:
    if raw.strip().lower() in {"all", "hepsi", ""}:
        return ind.ALL_INDICATORS
    keys = tuple(k.strip().lower() for k in raw.split(",") if k.strip())
    unknown = [k for k in keys if k not in ind.ALL_INDICATORS]
    if unknown:
        raise SystemExit(
            f"Bilinmeyen gosterge: {', '.join(unknown)}\n"
            f"Gecerli olanlar: {', '.join(ind.ALL_INDICATORS)}"
        )
    return keys


def _intervals(raw: str) -> list[str]:
    """'4h,1d,1wk' -> ['4h', '1d', '1wk']. Bosluk da ayirici sayilir.

    PowerShell tuzagi: tirnaksiz yazilan 4h,1d,1wk ifadesinde '1d' bir ONDALIK
    SAYI LITERALIDIR ve 1'e cevrilir; Python'a '4h,1,1wk' gelir. Bu yuzden
    ciplak sayi goruldugunde hata mesajinda tirnak kullanmasi hatirlatilir.
    """
    out: list[str] = []
    for item in raw.replace(",", " ").split():
        if item not in out:
            out.append(item)
    if not out:
        raise SystemExit("En az bir bar araligi gerekli")

    unknown = [i for i in out if i not in DEFAULT_PERIODS]
    if unknown:
        message = [
            f"Bilinmeyen aralik: {', '.join(unknown)}",
            f"Gecerli olanlar: {', '.join(DEFAULT_PERIODS)}",
        ]
        if any(i.isdigit() for i in unknown):
            message.append(
                "İpucu: PowerShell'de '1d' ondalık sayı literalidir ve 1'e dönüşür. "
                'Değeri tırnak içine alın: --interval "4h,1d,1wk"'
            )
        raise SystemExit("\n".join(message))
    return out


def _build_one(args, interval: str, theme, outdir: Path):
    """Tek bir bar araligi icin kareleri uretir ve dosyalari yazar."""
    bars = args.bars if args.bars else default_bars(interval)
    if args.indicators:
        view_set = build_chart(
            symbol=args.symbol, interval=interval, bars=bars,
            period=args.period, keys=resolve_keys(args.indicators),
            project_bars=args.project_bars, log_price=_scale(args.scale),
        )
    else:
        try:
            views = resolve_views(args.views)
        except KeyError as exc:
            raise SystemExit(str(exc)) from exc
        view_set = build_views(
            symbol=args.symbol, views=views, interval=interval,
            bars=bars, period=args.period, project_bars=args.project_bars,
            log_price=_scale(args.scale),
        )

    stem = f"{view_set.symbol.display.replace('-', '_')}_{interval}"
    png_paths: list[Path] = []
    grid_path: Path | None = None

    if not args.no_png:
        use_grid = args.grid > 0 and len(view_set) > 1
        tiles: list[Path] = []
        for i, result in enumerate(view_set, start=1):
            path = outdir / f"{stem}_{i:02d}_{result.key}.png"
            # Izgara karolarinda ust serit cizilmez; kimlik satir ici kunyede.
            render_png(result.spec, theme, path, width_px=args.width,
                       dpi=args.dpi, compact=use_grid)
            tiles.append(path)

        if use_grid:
            grid_path = outdir / f"{stem}_izgara.png"
            compose_grid(
                tiles, grid_path, theme, columns=args.grid,
                title=f"{view_set.symbol.display} · {INTERVAL_LABELS.get(interval, interval)}",
                subtitle=f"{view_set.subtitle} · {view_set.generated_at}",
            )
            png_paths = [grid_path]
        else:
            png_paths = tiles

    html_path = outdir / f"{stem}.html"
    if not args.no_html:
        render_html(
            frames=[(r.key, r.view.title, r.view.note, r.spec) for r in view_set],
            theme=theme, path=html_path,
            ticker=view_set.symbol.display, subtitle=view_set.subtitle,
            source=view_set.source_label, generated=view_set.generated_at,
            embed_js=args.embed_js,
        )

    return view_set, png_paths, grid_path, html_path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    theme = get_theme(args.theme)
    outdir = Path(args.outdir)
    intervals = _intervals(args.interval)

    if args.telegram:
        # Kimlik bilgisi kontrolu ISIN BASINDA yapilir. Sonda yapilirsa dort
        # periyodun grafikleri uretildikten sonra hata verir ve dakikalarca
        # suren is bosa gider.
        from .telegram import TelegramError, _credentials

        try:
            _credentials()
        except TelegramError as exc:
            raise SystemExit(f"Telegram gonderimi istendi ama yapilandirma eksik.\n{exc}")

    produced = []
    for interval in intervals:
        try:
            produced.append((interval,) + _build_one(args, interval, theme, outdir))
        except Exception as exc:  # noqa: BLE001
            # Bir aralik basarisiz olursa digerleri yine de uretilsin;
            # ornegin saatlik veri yoksa gunluk ve haftalik calismaya devam eder.
            print(f"HATA [{interval}]: {exc}")
            if len(intervals) == 1:
                raise

    if not produced:
        raise SystemExit("Hicbir aralik icin grafik uretilemedi")

    for _, _, png_paths, _, html_path in produced:
        for path in png_paths + ([html_path] if not args.no_html else []):
            print(f"yazildi: {path}  ({path.stat().st_size / 1024:.0f} KB)")

    if args.telegram:
        from .telegram import build_caption, send_document, send_media_group, send_photo

        for interval, view_set, png_paths, grid_path, html_path in produced:
            label = INTERVAL_LABELS.get(interval, interval)
            caption = build_caption(
                f"{view_set.symbol.display} · {label}",
                view_set.subtitle, view_set.results[0].spec.snapshot,
            )
            if png_paths:
                if len(png_paths) == 1:
                    # Izgara genis oldugu icin fotograf olarak gonderilirse
                    # Telegram uzun kenari ~1280'e indirir ve yazilar okunmaz olur.
                    if grid_path is not None:
                        send_document(png_paths[0], caption)
                    else:
                        send_photo(png_paths[0], caption)
                else:
                    send_media_group(png_paths, caption)
                print(f"telegram [{label}]: {len(png_paths)} gorsel gonderildi")
            if not args.no_html:
                send_document(html_path, f"{view_set.symbol.display} · {label} · etkileşimli")

    return 0


if __name__ == "__main__":
    sys.exit(main())
