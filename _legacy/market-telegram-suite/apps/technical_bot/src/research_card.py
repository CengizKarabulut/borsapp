"""Mobile-first integrated research summary card."""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

from src.research_engine import LevelZone, ResearchReport

BG = "#0b1220"
PANEL = "#111a2b"
TEXT = "#eef4fb"
MUTED = "#8fa2b8"
GRID = "#223047"
GREEN = "#39c98a"
RED = "#ff6577"
AMBER = "#f2bd4a"
TEAL = "#49d6d0"


def _colour(score: float | None) -> str:
    if score is None:
        return MUTED
    if score >= 70:
        return GREEN
    if score < 45:
        return RED
    return AMBER


def _stars(score: float | None) -> str:
    if score is None:
        return "☆☆☆☆☆"
    filled = max(0, min(5, round(score / 20)))
    return "★" * filled + "☆" * (5 - filled)


def _wrap(value: str, width: int = 78) -> str:
    return "\n".join(textwrap.wrap(str(value), width=width))


def _zone_text(zone: LevelZone) -> str:
    span = f"{zone.low:,.2f}" if abs(zone.high - zone.low) < 0.005 else f"{zone.low:,.2f}–{zone.high:,.2f}"
    source = "+".join(zone.sources[:4])
    return f"{span} · {zone.status} · Q{zone.score:.0f} · {source}"


def _panel(ax: plt.Axes) -> None:
    # Text and separator lines use data coordinates, so pin them explicitly.
    # Without fixed limits matplotlib autoscaling can move the first rows outside
    # the intended card even though the background patch uses axes coordinates.
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        FancyBboxPatch(
            (0, 0),
            1,
            1,
            boxstyle="round,pad=0.012,rounding_size=0.025",
            transform=ax.transAxes,
            facecolor=PANEL,
            edgecolor=GRID,
            linewidth=0.9,
        )
    )


def render_research_card(report: ResearchReport, output: Path) -> Path:
    """Render an overlap-safe dark summary card."""
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = "DejaVu Sans"
    fig = plt.figure(figsize=(9.0, 13.8), dpi=140, facecolor=BG)

    price = "—" if report.price is None else f"{report.price:,.2f} TL"
    score = "—" if report.research_score is None else f"{report.research_score:.0f}/100"
    fig.text(0.06, 0.955, report.symbol, fontsize=24, fontweight="bold", color=TEXT, va="top")
    fig.text(0.06, 0.918, price, fontsize=17, fontweight="bold", color=TEAL, va="top")
    fig.text(0.06, 0.887, _wrap(report.company_name, 48), fontsize=9.4, color=MUTED, va="top")
    fig.text(0.64, 0.946, "ARAŞTIRMA SKORU", fontsize=8.7, color=MUTED, ha="right")
    fig.text(0.64, 0.910, score, fontsize=21, fontweight="bold", color=_colour(report.research_score), ha="right")
    fig.text(0.94, 0.915, _stars(report.research_score), fontsize=18, color=TEAL, ha="right")
    fig.text(0.94, 0.882, f"Veri kapsamı %{round(report.coverage * 100)}", fontsize=8.7, color=MUTED, ha="right")

    dimensions_ax = fig.add_axes([0.055, 0.455, 0.89, 0.395])
    _panel(dimensions_ax)
    dimensions_ax.text(0.035, 0.955, "BEŞ BOYUTLU OKUMA", fontsize=10.5, color=TEAL, fontweight="bold", va="top")
    row_top = 0.82
    row_gap = 0.155
    for index, dimension in enumerate(report.dimensions):
        y = row_top - index * row_gap
        number = "—" if dimension.score is None else f"{dimension.score:.0f}/100"
        dimensions_ax.text(0.035, y, dimension.name, fontsize=11.4, fontweight="bold", color=TEXT, va="center")
        dimensions_ax.text(0.53, y, number, fontsize=10.6, fontweight="bold", color=_colour(dimension.score), va="center")
        dimensions_ax.text(0.965, y, dimension.label, fontsize=8.7, color=_colour(dimension.score), ha="right", va="center")
        dimensions_ax.text(0.035, y - 0.045, _wrap(dimension.summary, 88), fontsize=7.5, color=MUTED, va="top")
        if index < len(report.dimensions) - 1:
            dimensions_ax.plot([0.035, 0.965], [y - 0.085, y - 0.085], color=GRID, linewidth=0.65)

    risk_ax = fig.add_axes([0.055, 0.335, 0.89, 0.09])
    _panel(risk_ax)
    if report.main_risk is None:
        risk_ax.text(0.035, 0.68, "ANA RİSK", fontsize=10.7, color=MUTED, fontweight="bold")
        risk_ax.text(0.035, 0.28, "Risk verisi yetersiz.", fontsize=9.0, color=MUTED)
    else:
        risk_ax.text(0.035, 0.69, f"ANA RİSK · {report.main_risk.name}", fontsize=11.4, color=RED, fontweight="bold")
        risk_ax.text(0.965, 0.69, f"{report.main_risk.score:.0f}/100", fontsize=11.4, color=RED, fontweight="bold", ha="right")
        risk_ax.text(0.035, 0.25, _wrap(report.main_risk.evidence, 105), fontsize=8.2, color=TEXT, va="center")

    levels_ax = fig.add_axes([0.055, 0.145, 0.89, 0.155])
    _panel(levels_ax)
    levels_ax.text(0.035, 0.89, "KRİTİK SEVİYELER", fontsize=10.7, fontweight="bold", color=TEAL, va="top")
    y = 0.66
    if report.supports:
        for zone in report.supports[:2]:
            levels_ax.text(0.035, y, f"DESTEK  {_zone_text(zone)}", fontsize=8.4, color=GREEN, va="top")
            y -= 0.17
    else:
        levels_ax.text(0.035, y, "Destek · yakın ve yeterli kalite puanlı aktif bölge yok", fontsize=8.4, color=MUTED, va="top")
        y -= 0.17
    if report.resistances:
        for zone in report.resistances[:2]:
            levels_ax.text(0.035, y, f"DİRENÇ  {_zone_text(zone)}", fontsize=8.4, color=RED, va="top")
            y -= 0.17
    else:
        levels_ax.text(0.035, y, "Direnç · yakın ve yeterli kalite puanlı aktif bölge yok", fontsize=8.4, color=MUTED, va="top")

    financial = report.financial
    fig.text(
        0.06,
        0.112,
        f"Bilanço {financial.get('balance_label', '—')}   ·   Kâr kalitesi {financial.get('earnings_quality_label', '—')}   ·   Borç {financial.get('debt_direction', '—')}",
        fontsize=8.8,
        color=TEXT,
    )
    fig.text(0.06, 0.082, _wrap(report.note, 116), fontsize=7.4, color=MUTED, va="top")
    fig.text(
        0.5,
        0.025,
        "Teknik + bilanço + değerleme + şirket kalitesi + risk · otomatik AL/SAT değildir",
        fontsize=7.7,
        color=MUTED,
        ha="center",
    )
    fig.savefig(output, facecolor=BG, bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)
    return output
