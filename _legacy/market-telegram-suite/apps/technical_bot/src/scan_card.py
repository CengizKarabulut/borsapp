"""Research-style scan summary and candidate detail cards.

The scanner is a discovery surface, not a second copy of the full /analiz
report. Positive-direction candidates are shown first, conditional candidates
next and negative/risk candidates last. The cards explain why a symbol surfaced
without turning the scan into an AL/SAT engine.
"""

from __future__ import annotations

import math
import textwrap
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import FancyBboxPatch

from src.screener import SCREENS

BG = "#FFFFFF"
PANEL = "#F8FAFC"
PANEL_2 = "#F1F5F9"
GRID = "#D7E0EA"
TEXT = "#172033"
MUTED = "#64748B"
GREEN = "#15803D"
RED = "#C62828"
AMBER = "#B7791F"
ACCENT = "#0F6CBD"
TEAL = "#0F8A83"

ROWS_PER_PAGE = 5


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fmt(value: Any, digits: int = 2) -> str:
    number = _finite(value)
    return "—" if number is None else f"{number:,.{digits}f}"


def _short(value: Any, width: int) -> str:
    text = " ".join(str(value or "—").split())
    return textwrap.shorten(text, width=width, placeholder="…")


def _panel(
    ax: plt.Axes,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str = PANEL,
) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            width,
            height,
            boxstyle="round,pad=0.006,rounding_size=0.012",
            transform=ax.transAxes,
            facecolor=fill,
            edgecolor=GRID,
            linewidth=0.8,
        )
    )


def _screen_labels(item: dict[str, Any]) -> list[str]:
    labels = {name: SCREENS[name]["label"] for name in SCREENS}
    setup = str(item.get("setup", ""))
    values = [labels.get(name, name) for name in item.get("screens", [])]
    return [value for value in values if value.casefold() != setup.casefold()]


def _intervals(
    item: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> list[str]:
    values = list(item.get("matched_intervals", []) or [])
    if values:
        return values
    if payload:
        values = list(payload.get("intervals", []) or [])
        if values:
            return values
        interval = str(payload.get("interval", "")).strip()
        if interval:
            return [interval]
    return []


def _structure_text(item: dict[str, Any]) -> str:
    contexts = item.get("intervals") or {}
    if isinstance(contexts, dict) and contexts:
        parts: list[str] = []
        for interval, info in contexts.items():
            structure = (info or {}).get("structure", {})
            state = str(structure.get("state", "—"))
            event = str(structure.get("event", ""))
            part = f"{interval} {state}"
            if event and event != "Yeni yapı kırılımı yok":
                part += f" · {event}"
            parts.append(part)
        if parts:
            return " | ".join(parts)
    structure = item.get("structure") or {}
    state = str(structure.get("state", "—"))
    event = str(structure.get("event", "Yeni yapı kırılımı yok"))
    return f"{state} · {event}"


def _level_text(item: dict[str, Any]) -> str:
    levels = item.get("active_levels") or {}
    reference = _finite(levels.get("reference_close"))
    lower = _finite(levels.get("lower"))
    upper = _finite(levels.get("upper"))
    if (
        reference is None
        or lower is None
        or upper is None
        or not lower < reference < upper
    ):
        return (
            "Aktif iki taraflı yapı seviyesi doğrulanamadı; "
            "eski pivot aktif eşik olarak kullanılmıyor."
        )
    lower_source = str(levels.get("lower_source", "yapısal destek"))
    upper_source = str(levels.get("upper_source", "yapısal direnç"))
    return (
        f"Alt {_fmt(lower)} ({lower_source})  ·  Ref {_fmt(reference)}  ·  "
        f"Üst {_fmt(upper)} ({upper_source})"
    )


def _relative_strength(item: dict[str, Any]) -> str:
    excess = _finite(item.get("excess_return_20"))
    if excess is None:
        return "XU100 göreceli güç —"
    return f"XU100 {excess:+.1f} puan"


def _rvol_text(item: dict[str, Any]) -> str:
    projected = _finite(item.get("rvol"))
    observed = _finite(item.get("rvol_observed"))
    fraction = _finite(item.get("bar_fraction"))
    if projected is None:
        return "RVOL —"
    if fraction is not None and fraction < 1 and observed is not None:
        return (
            f"RVOL {observed:.2f}x gerçekleşen / "
            f"{projected:.2f}x projeksiyon"
        )
    return f"RVOL {projected:.2f}x"


def _structure_votes(item: dict[str, Any]) -> tuple[int, int]:
    positive = 0
    negative = 0
    contexts = item.get("intervals") or {}
    if isinstance(contexts, dict):
        for info in contexts.values():
            tone = str(
                ((info or {}).get("structure") or {}).get("tone", "")
            ).casefold()
            positive += tone == "positive"
            negative += tone == "negative"
    tone = str((item.get("structure") or {}).get("tone", "")).casefold()
    positive += tone == "positive"
    negative += tone == "negative"
    return positive, negative


def _direction_bucket(item: dict[str, Any]) -> int:
    """0=positive, 1=conditional/neutral, 2=negative."""
    bias = str(item.get("setup_bias", "")).casefold()
    if "yukarı" in bias or "pozitif" in bias:
        return 0
    if "aşağı" in bias or "negatif" in bias:
        return 2

    positive, negative = _structure_votes(item)
    if positive > negative:
        return 0
    if negative > positive:
        return 2
    return 1


def _direction_label(item: dict[str, Any]) -> str:
    return ("POZİTİF", "KARAR", "NEGATİF")[_direction_bucket(item)]


def _candidate_tone(item: dict[str, Any]) -> str:
    return (GREEN, AMBER, RED)[_direction_bucket(item)]


def candidate_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """Positive candidates first; quality decides order inside each group."""
    bucket = _direction_bucket(item)
    score = _finite(item.get("score")) or 0.0
    mtf = len(item.get("matched_intervals", []) or [])
    excess = _finite(item.get("excess_return_20")) or 0.0
    turnover = _finite(item.get("turnover")) or 0.0

    # Positive/conditional groups prefer positive relative strength.
    # Negative group prefers the most clearly negative relative strength.
    relative_key = -excess if bucket < 2 else excess
    return (bucket, -score, -mtf, relative_key, -turnover, str(item.get("ticker", "")))


def sort_scan_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=candidate_sort_key)


def _group_counts(items: list[dict[str, Any]]) -> tuple[int, int, int]:
    counts = [0, 0, 0]
    for item in items:
        counts[_direction_bucket(item)] += 1
    return counts[0], counts[1], counts[2]


def _candidate_commentary(
    item: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> str:
    bucket = _direction_bucket(item)
    setup = str(item.get("setup") or "Yön arayışı / geçiş")
    intervals = _intervals(item, payload)
    excess = _finite(item.get("excess_return_20"))
    rvol = _finite(item.get("rvol"))
    levels = item.get("active_levels") or {}
    lower = _finite(levels.get("lower"))
    reference = _finite(levels.get("reference_close"))
    upper = _finite(levels.get("upper"))
    valid_levels = (
        lower is not None
        and reference is not None
        and upper is not None
        and lower < reference < upper
    )

    if bucket == 0:
        parts = [f"Pozitif eğilim önde. {setup}."]
        if len(intervals) > 1:
            parts.append(
                f"{'+'.join(intervals)} zaman dilimlerinde birlikte öne çıkıyor."
            )
        if excess is not None:
            if excess >= 0.5:
                parts.append(f"XU100'a göre {excess:+.1f} puan güçlü.")
            elif excess <= -0.5:
                parts.append(
                    f"Ancak XU100'a göre {excess:+.1f} puan zayıf; kaliteyi düşürüyor."
                )
        if rvol is not None:
            if rvol >= 1.5:
                parts.append(f"RVOL {rvol:.1f}x ile katılım belirgin.")
            elif rvol < 1.0:
                parts.append("Hacim teyidi zayıf.")
        if valid_levels:
            parts.append(
                f"{_fmt(upper)} üstü kapanış kabulü görünümü güçlendirir; "
                f"{_fmt(lower)} altı zayıflatır."
            )
        return " ".join(parts)

    if bucket == 2:
        parts = [f"Risk/aşağı eğilim baskın. {setup}."]
        if len(intervals) > 1:
            parts.append(
                f"{'+'.join(intervals)} taramalarında aynı sembol tekrar öne çıkıyor."
            )
        if excess is not None:
            if excess <= -0.5:
                parts.append(f"XU100'a göre {excess:+.1f} puan zayıf.")
            elif excess >= 0.5:
                parts.append(
                    f"Endekse göre {excess:+.1f} puan güçlü olması aşağı okumayı yumuşatıyor."
                )
        if rvol is not None and rvol >= 1.5:
            parts.append(
                f"RVOL {rvol:.1f}x; hareketin önemi artıyor fakat hacim tek başına yön teyidi değil."
            )
        if valid_levels:
            parts.append(
                f"{_fmt(lower)} altı kapanış bozulmayı derinleştirir; "
                f"{_fmt(upper)} geri kazanımı riski azaltır."
            )
        return " ".join(parts)

    parts = [f"Yön henüz net değil. {setup}."]
    if len(intervals) > 1:
        parts.append(
            f"{'+'.join(intervals)} zaman dilimlerinde izlemeye değer ortak bir durum var."
        )
    if rvol is not None and rvol >= 1.5:
        parts.append(
            f"RVOL {rvol:.1f}x katılım gösteriyor; bu tek başına kırılım yönü söylemez."
        )
    if excess is not None:
        if excess >= 0.5:
            parts.append(f"XU100'a göre {excess:+.1f} puan güçlü.")
        elif excess <= -0.5:
            parts.append(f"XU100'a göre {excess:+.1f} puan zayıf.")
    if valid_levels:
        parts.append(
            f"{_fmt(upper)} üstü kabul pozitif, {_fmt(lower)} altı kabul negatif "
            "senaryoyu öne çıkarır."
        )
    return " ".join(parts)


def _summary_lines(
    payload: dict[str, Any],
    universe_source: str,
    elapsed: float,
    items: list[dict[str, Any]],
) -> tuple[str, str, str]:
    broken = len(payload.get("error_kinds", {}).get("ariza", []))
    illiquid = int(payload.get("illiquid", 0) or 0)
    no_match = int(payload.get("no_match", 0) or 0)
    positive, conditional, negative = _group_counts(items)
    overview = (
        f"Evren {payload.get('requested', 0)} · İşlenen {payload.get('processed', 0)} · "
        f"Eşleşen {payload.get('matched', 0)} · Pozitif {positive} · "
        f"Karar {conditional} · Negatif {negative} · Arıza {broken}"
    )
    options = payload.get("options") or {}
    filters = (
        f"Likidite {illiquid} · Koşul dışı {no_match} · "
        f"BB ≤ %{_fmt(options.get('bb_rank_max'), 0)} · "
        f"RVOL ≥ {_fmt(options.get('rvol_min'), 1)}x · "
        f"Hacim patlaması ≥ {_fmt(options.get('rvol_spike'), 1)}x · "
        f"Süre {elapsed / 60:.1f} dk"
    )
    intervals = payload.get("intervals") or [payload.get("interval", "1d")]
    context = (
        f"{' + '.join(str(value) for value in intervals if value)} · "
        f"{universe_source}"
    )
    return overview, filters, context


def _draw_header(
    fig: plt.Figure,
    ax: plt.Axes,
    payload: dict[str, Any],
    universe_source: str,
    elapsed: float,
    title: str,
    page_no: int,
    page_count: int,
    ordered_items: list[dict[str, Any]],
) -> float:
    stamp = str(payload.get("timestamp", ""))
    intervals = payload.get("intervals") or [payload.get("interval", "1d")]
    interval_text = " + ".join(str(value) for value in intervals if value)
    fig.text(
        0.06,
        0.965,
        title,
        fontsize=22,
        fontweight="bold",
        color=TEXT,
        va="top",
    )
    fig.text(
        0.94,
        0.965,
        f"{page_no}/{page_count}",
        fontsize=13,
        fontweight="bold",
        color=ACCENT,
        ha="right",
        va="top",
    )
    fig.text(
        0.06,
        0.928,
        f"{stamp} · {interval_text} tarama",
        fontsize=10.5,
        color=MUTED,
        va="top",
    )
    fig.text(
        0.94,
        0.928,
        "Pozitif adaylar önce",
        fontsize=9.2,
        fontweight="bold",
        color=GREEN,
        ha="right",
        va="top",
    )

    _panel(ax, 0.055, 0.805, 0.89, 0.095, fill=PANEL)
    overview, filters, context = _summary_lines(
        payload,
        universe_source,
        elapsed,
        ordered_items,
    )
    ax.text(
        0.075,
        0.877,
        "TARAMA BAĞLAMI",
        fontsize=9.3,
        color=ACCENT,
        fontweight="bold",
        va="top",
    )
    ax.text(0.075, 0.851, overview, fontsize=8.1, color=TEXT, va="top")
    ax.text(0.075, 0.828, filters, fontsize=7.4, color=MUTED, va="top")
    ax.text(
        0.925,
        0.877,
        context,
        fontsize=7.5,
        color=MUTED,
        ha="right",
        va="top",
    )

    freshness = payload.get("freshness") or {}
    if freshness.get("stale"):
        age = (_finite(freshness.get("age_minutes")) or 0.0) / 60.0
        ax.text(
            0.075,
            0.807,
            (
                f"Seans dışı / eski bar: son veri {age:.1f} saat önce. "
                "Hacim ve RVOL güncel seans teyidi değildir."
            ),
            fontsize=7.1,
            color=AMBER,
            fontweight="bold",
            va="bottom",
        )
    return 0.775


def _draw_candidate(
    ax: plt.Axes,
    item: dict[str, Any],
    rank: int,
    y: float,
    height: float,
    payload: dict[str, Any],
) -> None:
    _panel(ax, 0.055, y, 0.89, height, fill=BG)
    tone = _candidate_tone(item)
    label = _direction_label(item)
    ax.plot(
        [0.063, 0.063],
        [y + 0.014, y + height - 0.014],
        color=tone,
        linewidth=3.0,
        transform=ax.transAxes,
    )

    ticker = str(item.get("ticker", "—"))
    price = _fmt(item.get("close"))
    score = _fmt(item.get("score"), 1)
    ax.text(
        0.078,
        y + height - 0.021,
        f"{rank}.  {ticker}",
        fontsize=10.8,
        fontweight="bold",
        color=TEXT,
        va="top",
    )
    ax.text(
        0.285,
        y + height - 0.021,
        f"{price} TL",
        fontsize=9.5,
        fontweight="bold",
        color=tone,
        va="top",
    )
    ax.text(
        0.47,
        y + height - 0.021,
        label,
        fontsize=7.5,
        fontweight="bold",
        color=tone,
        va="top",
    )
    ax.text(
        0.925,
        y + height - 0.021,
        f"Tarama puanı {score}",
        fontsize=8.2,
        fontweight="bold",
        color=tone,
        ha="right",
        va="top",
    )

    commentary = _candidate_commentary(item, payload)
    wrapped = "\n".join(textwrap.wrap(commentary, width=116)[:2])
    ax.text(
        0.078,
        y + height - 0.048,
        f"YORUM: {wrapped}",
        fontsize=7.25,
        color=TEXT,
        fontweight="bold",
        va="top",
        linespacing=1.23,
    )

    matched_intervals = _intervals(item, payload)
    mtf = "+".join(matched_intervals) if matched_intervals else "—"
    bb = _fmt(item.get("bb_width_percentile"), 0)
    rsi = _fmt(item.get("rsi"), 1)
    atr = _fmt(item.get("atr_pct"), 1)
    metrics = (
        f"MTF {mtf} · {_rvol_text(item)} · BB %{bb} · RSI {rsi} · "
        f"ATR %{atr} · {_relative_strength(item)} · Yapı {_structure_text(item)}"
    )
    ax.text(
        0.078,
        y + 0.033,
        _short(metrics, 145),
        fontsize=6.95,
        color=MUTED,
        va="bottom",
    )
    ax.text(
        0.078,
        y + 0.014,
        _short(f"SEVİYELER: {_level_text(item)}", 145),
        fontsize=7.0,
        color=tone,
        va="bottom",
    )


def render_scan_cards(
    payload: dict[str, Any],
    directory: Path,
    universe_source: str,
    elapsed: float,
    title: str = "BIST Teknik Tarama",
    limit: int = 15,
    stem: str = "scan_card",
) -> list[Path]:
    """Render balanced cards and put positive candidates at the front."""
    directory.mkdir(parents=True, exist_ok=True)
    ordered_all = sort_scan_results(list(payload.get("results", [])))
    payload["results"] = ordered_all
    results = ordered_all[:limit]
    page_count = max(1, math.ceil(len(results) / ROWS_PER_PAGE))
    paths: list[Path] = []

    for page_index in range(page_count):
        page_items = results[
            page_index * ROWS_PER_PAGE : (page_index + 1) * ROWS_PER_PAGE
        ]
        fig = plt.figure(figsize=(9.0, 13.2), dpi=140, facecolor=BG)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis("off")
        top = _draw_header(
            fig,
            ax,
            payload,
            universe_source,
            elapsed,
            title,
            page_index + 1,
            page_count,
            ordered_all,
        )

        if page_items:
            row_height = 0.132
            gap = 0.012
            y = top - row_height
            for local_index, item in enumerate(page_items):
                rank = page_index * ROWS_PER_PAGE + local_index + 1
                _draw_candidate(ax, item, rank, y, row_height, payload)
                y -= row_height + gap
        else:
            _panel(ax, 0.055, 0.57, 0.89, 0.16, fill=PANEL)
            ax.text(
                0.5,
                0.655,
                "Bu taramada koşulları karşılayan sembol bulunamadı.",
                fontsize=11,
                color=MUTED,
                ha="center",
            )

        if page_index == page_count - 1:
            actions = payload.get("corporate_actions", [])
            if actions:
                ax.text(
                    0.06,
                    0.055,
                    _short(
                        (
                            "Veri bütünlüğü filtresi: bölünme/sermaye artırımı "
                            f"şüphesiyle dışarıda: {', '.join(actions[:10])}"
                        ),
                        145,
                    ),
                    fontsize=7.2,
                    color=RED,
                )
        fig.text(
            0.5,
            0.022,
            (
                "Durum taramasıdır · AL/SAT değildir · pozitif sıralama yön teyidi "
                "değil, araştırma önceliğidir"
            ),
            fontsize=7.2,
            color=MUTED,
            ha="center",
        )
        path = directory / f"{stem}_{page_index + 1}.png"
        fig.savefig(path, facecolor=BG)
        plt.close(fig)
        paths.append(path)
    return paths


def _draw_detail_panel(
    ax: plt.Axes,
    y: float,
    height: float,
    title: str,
    body: str,
    *,
    title_colour: str = ACCENT,
) -> None:
    _panel(ax, 0.055, y, 0.89, height, fill=PANEL)
    ax.text(
        0.075,
        y + height - 0.022,
        title,
        fontsize=9.2,
        color=title_colour,
        fontweight="bold",
        va="top",
    )
    wrapped = "\n".join(textwrap.wrap(" ".join(body.split()), width=112))
    ax.text(
        0.075,
        y + height - 0.052,
        wrapped,
        fontsize=7.8,
        color=TEXT,
        va="top",
        linespacing=1.35,
    )


def render_scan_detail_card(
    item: dict[str, Any],
    prices: pd.DataFrame,
    output: Path,
    interval: str,
) -> Path:
    """Render one concise scan-candidate card from already downloaded prices."""
    output.parent.mkdir(parents=True, exist_ok=True)
    ticker = str(item.get("ticker", "—"))
    tone = _candidate_tone(item)
    label = _direction_label(item)
    fig = plt.figure(figsize=(9.0, 12.8), dpi=140, facecolor=BG)
    canvas = fig.add_axes([0, 0, 1, 1])
    canvas.set_xlim(0, 1)
    canvas.set_ylim(0, 1)
    canvas.axis("off")

    fig.text(
        0.06,
        0.965,
        f"{ticker} — Tarama Adayı",
        fontsize=22,
        fontweight="bold",
        color=TEXT,
        va="top",
    )
    fig.text(
        0.06,
        0.925,
        f"{_fmt(item.get('close'))} TL",
        fontsize=15,
        fontweight="bold",
        color=tone,
        va="top",
    )
    fig.text(
        0.25,
        0.925,
        f"{interval} · {label} · tarama puanı {_fmt(item.get('score'), 1)}",
        fontsize=9.5,
        color=tone,
        fontweight="bold",
        va="top",
    )
    fig.text(
        0.94,
        0.925,
        "TARAMA → ARAŞTIRMA KÖPRÜSÜ",
        fontsize=8.4,
        color=ACCENT,
        fontweight="bold",
        ha="right",
        va="top",
    )

    _draw_detail_panel(
        canvas,
        0.815,
        0.075,
        "İLK OKUMA",
        _candidate_commentary(item, {"interval": interval}),
        title_colour=tone,
    )

    chart = fig.add_axes([0.075, 0.515, 0.85, 0.265], facecolor=BG)
    frame = prices.dropna(subset=["Close"]).tail(100).copy()
    if not frame.empty:
        close = frame["Close"].astype(float)
        chart.plot(
            close.index,
            close,
            color=TEXT,
            linewidth=1.7,
            label="Kapanış",
        )
        ma21 = close.rolling(21).mean()
        ma55 = close.rolling(55).mean()
        chart.plot(
            ma21.index,
            ma21,
            color=ACCENT,
            linewidth=1.0,
            label="MA21",
        )
        chart.plot(
            ma55.index,
            ma55,
            color=AMBER,
            linewidth=1.0,
            label="MA55",
        )
        if "Low" in frame and "High" in frame:
            chart.fill_between(
                frame.index,
                frame["Low"],
                frame["High"],
                color=PANEL_2,
                alpha=0.65,
                linewidth=0,
            )
        levels = item.get("active_levels") or {}
        reference = _finite(levels.get("reference_close"))
        lower = _finite(levels.get("lower"))
        upper = _finite(levels.get("upper"))
        if (
            reference is not None
            and lower is not None
            and upper is not None
            and lower < reference < upper
        ):
            chart.axhline(
                lower,
                color=GREEN,
                linewidth=1.0,
                linestyle="--",
                label=f"Alt {_fmt(lower)}",
            )
            chart.axhline(
                upper,
                color=RED,
                linewidth=1.0,
                linestyle="--",
                label=f"Üst {_fmt(upper)}",
            )
        chart.legend(
            loc="upper left",
            frameon=False,
            fontsize=7,
            ncol=3,
        )
    chart.grid(color=GRID, linewidth=0.6, alpha=0.8)
    chart.tick_params(axis="both", labelsize=7, colors=MUTED)
    for spine in chart.spines.values():
        spine.set_color(GRID)
    chart.set_title(
        "Son 100 bar · kapanış + MA21/55 + doğrulanmış aktif seviyeler",
        fontsize=8.5,
        color=MUTED,
        loc="left",
        pad=8,
    )

    contexts = item.get("intervals") or {}
    if contexts:
        pieces = []
        for key, info in contexts.items():
            structure = (info or {}).get("structure", {})
            pieces.append(
                f"{key}: {structure.get('state', '—')} / "
                f"{structure.get('event', 'Yeni yapı kırılımı yok')} / "
                f"RVOL {_fmt((info or {}).get('rvol'))}x"
            )
        mtf_body = " | ".join(pieces)
    else:
        mtf_body = f"{interval}: {_structure_text(item)}"
    _draw_detail_panel(
        canvas,
        0.405,
        0.085,
        "ZAMAN DİLİMİ + PİYASA YAPISI",
        mtf_body,
    )

    profile = item.get("profile") or {}
    profile_text = (
        f"POC {_fmt(profile.get('poc'))} · VAH {_fmt(profile.get('vah'))} · "
        f"VAL {_fmt(profile.get('val'))} · "
        f"{profile.get('position', 'profil konumu —')} · "
        f"{profile.get('acceptance', 'kabul teyidi —')}"
    )
    level_body = f"{_level_text(item)}  |  {profile_text}"
    _draw_detail_panel(
        canvas,
        0.292,
        0.09,
        "AKTİF SEVİYELER + HACİM PROFİLİ",
        level_body,
        title_colour=TEAL,
    )

    metrics = (
        f"{_rvol_text(item)} · "
        f"BB genişlik %{_fmt(item.get('bb_width_percentile'), 0)} · "
        f"RSI {_fmt(item.get('rsi'), 1)} · "
        f"ATR %{_fmt(item.get('atr_pct'), 1)} · "
        f"{_relative_strength(item)}"
    )
    _draw_detail_panel(
        canvas,
        0.195,
        0.075,
        "KATILIM + MOMENTUM",
        metrics,
    )

    notes = list(item.get("notes", []) or [])
    confirmation = (
        "Tarama eşleşmesi tek başına yön kararı değildir. Seviyenin kapanışla "
        "kabulü, yapı olayının devamı ve hacim katılımı birlikte teyit aranmalıdır."
    )
    if notes:
        confirmation += " Not: " + " ".join(str(note) for note in notes[:2])
    _draw_detail_panel(
        canvas,
        0.085,
        0.085,
        "NEYİ BEKLEMELİ?",
        confirmation,
        title_colour=AMBER,
    )

    fig.text(
        0.5,
        0.032,
        (
            "Tam şirket + bilanço + değerleme + teknik yapı araştırması için: "
            f"/analiz {ticker}"
        ),
        fontsize=8.6,
        color=ACCENT,
        fontweight="bold",
        ha="center",
    )
    fig.text(
        0.5,
        0.014,
        "Durum taramasıdır; otomatik AL/SAT veya yatırım tavsiyesi değildir.",
        fontsize=7.0,
        color=MUTED,
        ha="center",
    )
    fig.savefig(output, facecolor=BG)
    plt.close(fig)
    return output
