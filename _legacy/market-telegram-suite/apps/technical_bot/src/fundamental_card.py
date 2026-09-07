"""Mobile-first fundamental analysis card renderer."""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch

from src.fundamental_analysis import Factor, FundamentalReport

BG = "#f5f7f8"
PANEL = "#ffffff"
TEXT = "#263238"
MUTED = "#78909c"
GRID = "#d9e1e5"
TEAL = "#42b8b5"
TEAL_DARK = "#168d89"
GREEN = "#2e9f6b"
RED = "#d9534f"
AMBER = "#d99a21"


def _stars(score: float | None) -> str:
    if score is None:
        return "☆☆☆☆☆"
    filled = int(np.clip(round(score), 0, 5))
    return "★" * filled + "☆" * (5 - filled)


def _score_colour(score: float | None) -> str:
    if score is None:
        return MUTED
    if score >= 3.6:
        return GREEN
    if score <= 1.8:
        return RED
    if score < 2.7:
        return AMBER
    return TEAL_DARK


def _wrapped(text: str, width: int = 58) -> str:
    return "\n".join(textwrap.wrap(str(text), width=width))


def _profile_label(profile: str) -> str:
    return {
        "BANK": "BANKA TEMEL PROFİLİ",
        "GYO": "GYO TEMEL PROFİLİ",
        "GENERIC": "ŞİRKET TEMEL PROFİLİ",
    }.get(profile, "TEMEL PROFİL")


def _radar(fig: plt.Figure, factors: tuple[Factor, ...]) -> None:
    ax = fig.add_axes([0.19, 0.60, 0.62, 0.245], polar=True)
    labels = [
        factor.name if factor.score is not None else f"{factor.name}\n(veri yetersiz)"
        for factor in factors
    ]
    values = [factor.score if factor.score is not None else 0.0 for factor in factors]
    count = len(labels)
    angles = np.linspace(0, 2 * np.pi, count, endpoint=False).tolist()
    angles += angles[:1]
    values += values[:1]

    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)
    ax.set_ylim(0, 5)
    ax.set_yticks([1, 2, 3, 4, 5])
    ax.set_yticklabels([])
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels([_wrapped(label, 17) for label in labels], fontsize=10.2, color=MUTED)
    ax.grid(color=GRID, linewidth=0.9)
    ax.spines["polar"].set_color(GRID)
    ax.set_facecolor(PANEL)
    ax.plot(angles, values, color=TEAL_DARK, linewidth=2.2)
    ax.fill(angles, values, color=TEAL, alpha=0.42)
    ax.scatter(angles[:-1], values[:-1], s=24, color=TEAL_DARK, zorder=3)


def _factor_rows(fig: plt.Figure, factors: tuple[Factor, ...]) -> None:
    ax = fig.add_axes([0.055, 0.265, 0.89, 0.31])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    centres = [0.90, 0.71, 0.52, 0.33, 0.14]
    for factor, y in zip(factors, centres, strict=False):
        ax.add_patch(
            FancyBboxPatch(
                (0.0, y - 0.075),
                1.0,
                0.15,
                boxstyle="round,pad=0.012,rounding_size=0.018",
                transform=ax.transAxes,
                facecolor=PANEL,
                edgecolor="#e8edef",
                linewidth=0.9,
            )
        )
        numeric = "Veri yetersiz" if factor.score is None else f"{factor.score:.2f}/5"
        numeric_size = 10.6 if factor.score is None else 12.3
        ax.text(0.035, y + 0.018, factor.name, fontsize=12.6, fontweight="bold", color=TEXT, va="center")
        ax.text(
            0.515,
            y + 0.018,
            numeric,
            fontsize=numeric_size,
            color=_score_colour(factor.score),
            va="center",
        )
        ax.text(0.965, y + 0.018, _stars(factor.score), fontsize=14.2, color=TEAL_DARK, va="center", ha="right")
        if factor.detail:
            ax.text(0.035, y - 0.038, _wrapped(factor.detail, 86), fontsize=8.2, color=MUTED, va="center")


def _insights(fig: plt.Figure, report: FundamentalReport) -> None:
    ax = fig.add_axes([0.065, 0.075, 0.87, 0.165])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(
        FancyBboxPatch(
            (0, 0.20),
            1,
            0.78,
            boxstyle="round,pad=0.012,rounding_size=0.02",
            transform=ax.transAxes,
            facecolor=PANEL,
            edgecolor="#e8edef",
            linewidth=0.9,
        )
    )

    positives = list(report.positives) or ["Belirgin güçlü faktör için veri teyidi sınırlı."]
    risks = list(report.risks)
    entries: list[tuple[str, str, str]] = []
    entries.extend(("✓", item, GREEN) for item in positives[:2])
    entries.extend(("!", item, RED) for item in risks[:2])
    if not risks:
        entries.append(("•", "Belirgin zayıf faktör saptanmadı; eksik veriler ayrıca izlenmeli.", MUTED))
    entries = entries[:4]

    y = 0.88
    for icon, item, colour in entries:
        ax.text(0.025, y, icon, fontsize=12.5, color=colour, fontweight="bold", va="top")
        ax.text(0.065, y, _wrapped(item, 78), fontsize=9.6, color=TEXT, va="top")
        y -= 0.18

    coverage = round(report.coverage * 100)
    footer = f"Veri kapsamı %{coverage} · {report.note}"
    ax.text(0.0, 0.03, _wrapped(footer, 115), fontsize=8.0, color=MUTED, va="bottom")


def render_fundamental_card(report: FundamentalReport, output: Path) -> Path:
    """Render one Telegram-friendly PNG similar to a mobile fundamentals tab."""
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = "DejaVu Sans"
    fig = plt.figure(figsize=(8.5, 14.4), dpi=140, facecolor=BG)

    company = report.company_name if report.company_name != report.symbol else ""
    price = "—" if report.price is None else f"{report.price:,.2f}"
    score = "—" if report.overall_score is None else f"{report.overall_score:.2f}/5"
    fig.text(0.065, 0.963, f"{report.symbol} · {price}", fontsize=21.5, fontweight="bold", color=TEXT, va="top")
    if company:
        fig.text(0.065, 0.934, _wrapped(company, 52), fontsize=10.8, color=MUTED, va="top")
    fig.text(0.065, 0.905, _profile_label(report.profile), fontsize=10.0, color=TEAL_DARK, fontweight="bold")

    fig.text(0.065, 0.865, "Genel Skor", fontsize=13.3, color=TEXT, fontweight="bold")
    fig.text(0.58, 0.865, score, fontsize=17.2, color=_score_colour(report.overall_score), fontweight="bold")
    fig.text(0.93, 0.865, _stars(report.overall_score), fontsize=16.2, color=TEAL_DARK, ha="right")

    _radar(fig, report.factors)
    _factor_rows(fig, report.factors)
    _insights(fig, report)

    fig.text(
        0.5,
        0.025,
        "Temel durum özeti · otomatik AL/SAT sinyali değildir · yatırım tavsiyesi değildir",
        fontsize=8.0,
        color=MUTED,
        ha="center",
    )
    fig.savefig(output, facecolor=BG, bbox_inches="tight", pad_inches=0.16)
    plt.close(fig)
    return output
