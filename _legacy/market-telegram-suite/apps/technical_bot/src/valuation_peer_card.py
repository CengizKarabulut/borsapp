"""Valuation-multiple and sector/competitor comparison card."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from src.research_engine import ResearchReport

BG = "#FFFFFF"
PANEL = "#F7F8FA"
TEXT = "#16181D"
MUTED = "#68707C"
BORDER = "#E3E6EA"
GREEN = "#118A5B"
AMBER = "#B26A00"
RED = "#B42318"
BLUE = "#2367C9"

LABELS = {
    "pe": "F/K",
    "pb": "PD/DD",
    "ev_ebitda": "FD/FAVÖK",
    "ev_sales": "FD/Satış",
    "ps": "Fiyat/Satış",
    "p_fcf": "Fiyat/FCF",
    "peg": "PEG",
    "dividend_yield": "Temettü",
    "earnings_yield": "Kazanç Verimi",
    "fcf_yield": "FCF Verimi",
    "roe": "ROE",
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _fmt(value: Any, key: str = "") -> str:
    number = _finite(value)
    if number is None:
        return "—"
    if key in {"dividend_yield", "earnings_yield", "fcf_yield", "roe"}:
        return f"%{number:,.1f}"
    return f"{number:,.2f}x"


def _box(ax, x: float, y: float, w: float, h: float) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.006,rounding_size=0.012",
            linewidth=0.8,
            edgecolor=BORDER,
            facecolor=PANEL,
            transform=ax.transAxes,
        )
    )


def _percentile_tone(key: str, percentile: float | None) -> tuple[str, str]:
    if percentile is None:
        return MUTED, "Karşılaştırma yok"
    if key == "roe":
        if percentile >= 75:
            return GREEN, "Sektör üst çeyrek"
        if percentile <= 25:
            return RED, "Sektör alt çeyrek"
        return BLUE, "Sektör orta bant"
    if percentile <= 25:
        return GREEN, "Sektöre göre düşük çarpan"
    if percentile >= 75:
        return RED, "Sektöre göre yüksek çarpan"
    return BLUE, "Sektör orta bant"


def render_valuation_peer_card(report: ResearchReport, output: str | Path) -> Path:
    """Render expanded multiples, sector benchmarks and named peers."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(12, 15), dpi=160, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_facecolor(BG)

    valuation = report.valuation
    metrics = valuation.get("metrics", {})
    peer = valuation.get("peer_analysis", {})
    scope = str(peer.get("scope") or valuation.get("scope") or "Karşılaştırma yok")

    ax.text(
        0.05,
        0.966,
        f"{report.symbol} · Değerleme ve Rakip Analizi",
        fontsize=22,
        fontweight="bold",
        color=TEXT,
        va="top",
    )
    ax.text(
        0.05,
        0.922,
        f"Karşılaştırma evreni: {scope} · mutlak çarpan + sektör yüzdeliği birlikte",
        fontsize=10.5,
        color=MUTED,
        va="top",
    )

    keys = (
        "pe",
        "pb",
        "ev_ebitda",
        "ev_sales",
        "ps",
        "p_fcf",
        "peg",
        "dividend_yield",
        "earnings_yield",
        "fcf_yield",
    )
    x0, y0 = 0.05, 0.820
    card_w, card_h = 0.168, 0.080
    gap_x, gap_y = 0.015, 0.012
    for idx, key in enumerate(keys):
        row_idx, col_idx = divmod(idx, 5)
        x = x0 + col_idx * (card_w + gap_x)
        y = y0 - row_idx * (card_h + gap_y)
        _box(ax, x, y, card_w, card_h)
        item = metrics.get(key, {})
        value = item.get("value") if isinstance(item, dict) else None
        percentile = _finite(item.get("percentile")) if isinstance(item, dict) else None
        tone, phrase = _percentile_tone(key, percentile)
        if key in {"peg", "ps", "p_fcf", "earnings_yield", "fcf_yield"} and percentile is None:
            tone = BLUE if _finite(value) is not None else MUTED
            phrase = "Bilanço/fiyat üzerinden hesaplandı" if _finite(value) is not None else "Hesaplanamadı"
        ax.text(
            x + 0.012,
            y + 0.059,
            LABELS[key],
            fontsize=8.3,
            fontweight="bold",
            color=TEXT,
            transform=ax.transAxes,
        )
        ax.text(
            x + 0.012,
            y + 0.033,
            _fmt(value, key),
            fontsize=13,
            fontweight="bold",
            color=tone,
            transform=ax.transAxes,
        )
        ax.text(x + 0.012, y + 0.010, phrase, fontsize=6.2, color=MUTED, transform=ax.transAxes)

    bench_y = 0.480
    bench_h = 0.205
    _box(ax, 0.05, bench_y, 0.90, bench_h)
    ax.text(
        0.072,
        bench_y + 0.172,
        "Sektör Karşılaştırması",
        fontsize=13,
        fontweight="bold",
        color=TEXT,
        transform=ax.transAxes,
    )
    ax.text(0.072, bench_y + 0.148, "Metrik", fontsize=7.4, fontweight="bold", color=MUTED, transform=ax.transAxes)
    ax.text(
        0.36,
        bench_y + 0.148,
        report.symbol,
        fontsize=7.4,
        fontweight="bold",
        color=MUTED,
        transform=ax.transAxes,
        ha="right",
    )
    ax.text(0.53, bench_y + 0.148, "Medyan", fontsize=7.4, fontweight="bold", color=MUTED, transform=ax.transAxes, ha="right")
    ax.text(0.69, bench_y + 0.148, "Yüzdelik", fontsize=7.4, fontweight="bold", color=MUTED, transform=ax.transAxes, ha="right")
    ax.text(0.92, bench_y + 0.148, "Okuma", fontsize=7.4, fontweight="bold", color=MUTED, transform=ax.transAxes, ha="right")

    benchmarks = peer.get("benchmarks", {})
    row_y = bench_y + 0.121
    for key in ("pe", "pb", "ev_ebitda", "ev_sales", "roe"):
        bench = benchmarks.get(key, {})
        target = _finite(bench.get("target")) if isinstance(bench, dict) else None
        median = _finite(bench.get("median")) if isinstance(bench, dict) else None
        percentile = _finite(bench.get("percentile")) if isinstance(bench, dict) else None
        tone, phrase = _percentile_tone(key, percentile)
        ax.text(0.072, row_y, LABELS[key], fontsize=8.3, color=TEXT, transform=ax.transAxes)
        ax.text(
            0.36,
            row_y,
            _fmt(target, key),
            fontsize=8.3,
            fontweight="bold",
            color=tone,
            transform=ax.transAxes,
            ha="right",
        )
        ax.text(0.53, row_y, _fmt(median, key), fontsize=8.3, color=TEXT, transform=ax.transAxes, ha="right")
        ax.text(
            0.69,
            row_y,
            "—" if percentile is None else f"%{percentile:.0f}",
            fontsize=8.3,
            color=TEXT,
            transform=ax.transAxes,
            ha="right",
        )
        ax.text(0.92, row_y, phrase, fontsize=7.2, color=tone, transform=ax.transAxes, ha="right")
        row_y -= 0.025

    peers_y = 0.125
    peers_h = 0.325
    _box(ax, 0.05, peers_y, 0.90, peers_h)
    ax.text(
        0.072,
        peers_y + peers_h - 0.035,
        "Rakip / Sektör Tablosu",
        fontsize=13,
        fontweight="bold",
        color=TEXT,
        transform=ax.transAxes,
    )
    headers = (
        ("Hisse", 0.075),
        ("F/K", 0.34),
        ("PD/DD", 0.46),
        ("FD/FAVÖK", 0.60),
        ("FD/Satış", 0.75),
        ("ROE", 0.91),
    )
    for label, x in headers:
        ax.text(
            x,
            peers_y + peers_h - 0.067,
            label,
            fontsize=7.2,
            fontweight="bold",
            color=MUTED,
            transform=ax.transAxes,
            ha="right" if x > 0.1 else "left",
        )
    row_y = peers_y + peers_h - 0.098
    peers = list(peer.get("peers", ()))[:8]
    if not peers:
        ax.text(
            0.075,
            row_y,
            "Karşılaştırılabilir rakip verisi bulunamadı.",
            fontsize=9,
            color=MUTED,
            transform=ax.transAxes,
        )
    for item in peers:
        symbol = str(item.get("symbol", ""))
        is_target = symbol == report.symbol
        color = BLUE if is_target else TEXT
        weight = "bold" if is_target else "normal"
        ax.text(0.075, row_y, symbol, fontsize=8.0, fontweight=weight, color=color, transform=ax.transAxes)
        ax.text(0.34, row_y, _fmt(item.get("pe"), "pe"), fontsize=7.8, color=color, transform=ax.transAxes, ha="right")
        ax.text(0.46, row_y, _fmt(item.get("pb"), "pb"), fontsize=7.8, color=color, transform=ax.transAxes, ha="right")
        ax.text(0.60, row_y, _fmt(item.get("ev_ebitda"), "ev_ebitda"), fontsize=7.8, color=color, transform=ax.transAxes, ha="right")
        ax.text(0.75, row_y, _fmt(item.get("ev_sales"), "ev_sales"), fontsize=7.8, color=color, transform=ax.transAxes, ha="right")
        ax.text(0.91, row_y, _fmt(item.get("roe"), "roe"), fontsize=7.8, color=color, transform=ax.transAxes, ha="right")
        row_y -= 0.030

    score = valuation.get("score")
    coverage = _finite(valuation.get("coverage"))
    score_text = "—" if _finite(score) is None else f"{float(score):.0f}/100"
    coverage_text = "—" if coverage is None else f"%{coverage * 100:.0f}"
    ax.text(
        0.05,
        0.095,
        f"Göreli değerleme skoru {score_text} · kapsam {coverage_text}",
        fontsize=10.5,
        fontweight="bold",
        color=TEXT,
        transform=ax.transAxes,
    )
    ax.text(0.05, 0.066, str(valuation.get("note", "")), fontsize=7.7, color=MUTED, transform=ax.transAxes, wrap=True)
    ax.text(0.05, 0.041, str(valuation.get("peg_note", "")), fontsize=6.9, color=MUTED, transform=ax.transAxes, wrap=True)
    ax.text(
        0.05,
        0.015,
        "Düşük çarpan tek başına olumlu kabul edilmez; büyüme, kârlılık, borç ve nakit kalitesi ile birlikte yorumlanır.",
        fontsize=7.1,
        color=MUTED,
        transform=ax.transAxes,
        va="bottom",
    )

    fig.savefig(path, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return path
