"""White research card for statement-derived ratios and forensic scores."""

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


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def _fmt(value: Any, unit: str) -> str:
    number = _finite(value)
    if number is None:
        return "—"
    if unit == "%":
        return f"%{number:,.1f}"
    if unit == "x":
        return f"{number:,.2f}x"
    if unit == "₺":
        return f"₺{number:,.2f}"
    return f"{number:,.2f}"


def _tone(key: str, value: Any) -> tuple[str, str]:
    number = _finite(value)
    if number is None:
        return MUTED, "Veri yok"
    if key == "current_ratio":
        if number < 1.0:
            return RED, "Kısa vadeli yükümlülük baskısı"
        if number < 1.4:
            return AMBER, "Likidite tamponu sınırlı"
        if number <= 3.0:
            return GREEN, "Likidite tamponu yeterli"
        return BLUE, "Likidite yüksek; sermaye verimliliği de izlenmeli"
    if key in {"quick_ratio", "cash_ratio"}:
        if number < 0.5:
            return AMBER, "Nakit/likit tampon sınırlı"
        return GREEN, "Likidite tamponu destekleyici"
    if key == "financial_debt_ratio":
        if number > 50:
            return RED, "Finansal borç yükü yüksek"
        if number > 30:
            return AMBER, "Borç yükü izlenmeli"
        return GREEN, "Finansal borç yükü görece sınırlı"
    if key == "net_debt_ebitda":
        if number > 4:
            return RED, "Borç servis kapasitesi zorlanabilir"
        if number > 2.5:
            return AMBER, "Kaldıraç orta-yüksek"
        return GREEN, "Borç/FAVÖK taşınabilir aralıkta"
    if key == "interest_coverage":
        if number < 1.5:
            return RED, "Faiz karşılama zayıf"
        if number < 3:
            return AMBER, "Faiz tamponu sınırlı"
        return GREEN, "Faiz karşılama rahat"
    if key in {"roa", "roe", "roic"}:
        if number <= 0:
            return RED, "Kârlılık negatif/zayıf"
        if number < 10:
            return AMBER, "Kârlılık sınırlı"
        return GREEN, "Kârlılık destekleyici"
    if "margin" in key:
        if number < 0:
            return RED, "Negatif marj"
        return GREEN, "Pozitif marj"
    return TEXT, ""


def _box(ax, x: float, y: float, w: float, h: float, *, radius: float = 0.012) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle=f"round,pad=0.006,rounding_size={radius}",
            linewidth=0.8,
            edgecolor=BORDER,
            facecolor=PANEL,
            transform=ax.transAxes,
        )
    )


def _draw_ratio_group(ax, group: dict[str, Any], x: float, y: float, w: float, row_h: float) -> float:
    rows = list(group.get("rows", ()))
    title_h = row_h * 0.95
    height = title_h + row_h * len(rows) + 0.018
    _box(ax, x, y - height, w, height)
    ax.text(
        x + 0.016,
        y - 0.020,
        str(group.get("name", "")),
        transform=ax.transAxes,
        fontsize=10.8,
        fontweight="bold",
        color=TEXT,
        va="top",
    )
    cursor = y - title_h
    for row in rows:
        value = row.get("value")
        tone, note = _tone(str(row.get("key", "")), value)
        ax.text(
            x + 0.016,
            cursor - 0.006,
            str(row.get("label", "")),
            transform=ax.transAxes,
            fontsize=8.4,
            color=TEXT,
            va="top",
        )
        ax.text(
            x + w - 0.016,
            cursor - 0.006,
            _fmt(value, str(row.get("unit", ""))),
            transform=ax.transAxes,
            fontsize=8.8,
            fontweight="bold",
            color=tone,
            ha="right",
            va="top",
        )
        if note:
            ax.text(
                x + 0.016,
                cursor - 0.021,
                note,
                transform=ax.transAxes,
                fontsize=5.9,
                color=MUTED,
                va="top",
            )
        cursor -= row_h
    return y - height - 0.014


def _score_value(score: dict[str, Any], kind: str) -> tuple[str, str, str]:
    if kind == "piotroski_f":
        value = score.get("score")
        max_score = score.get("max_score", 0)
        if value is None or not max_score:
            return "—", "Veri yetersiz", MUTED
        text = f"{int(value)}/{int(max_score)}"
        official = score.get("official_score")
        note = f"Resmî F-Skor {official}/9" if official is not None else "Kısmi gözlem; eksik ölçüt puanlanmadı"
        tone = GREEN if value / max_score >= 0.67 else RED if value / max_score <= 0.33 else AMBER
        return text, note, tone
    value = _finite(score.get("value"))
    if value is None:
        return "—", str(score.get("label", "Veri yetersiz")), MUTED
    if kind == "altman_z":
        tone = GREEN if value > 2.99 else RED if value < 1.81 else AMBER
    elif kind == "beneish_m":
        tone = GREEN if value < -1.78 else AMBER
    elif kind == "beta":
        tone = AMBER if value > 1.25 else GREEN if value < 1.0 else BLUE
    else:
        tone = BLUE
    return f"{value:,.3f}", str(score.get("label", "")), tone


def render_financial_intelligence_card(report: ResearchReport, output: str | Path) -> Path:
    """Render liquidity/leverage/efficiency/profitability plus forensic diagnostics."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(12, 18), dpi=160, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_facecolor(BG)

    ax.text(
        0.05,
        0.966,
        f"{report.symbol} · Finansal Oranlar ve Skorlar",
        fontsize=22,
        fontweight="bold",
        color=TEXT,
        va="top",
    )
    ax.text(
        0.05,
        0.936,
        "Bilanço + gelir tablosu + nakit akışı · TTM ve son çeyrek birlikte",
        fontsize=10.5,
        color=MUTED,
        va="top",
    )

    financial = report.financial
    groups = list(financial.get("ratio_groups", ()))
    if report.profile == "BANK" and not groups:
        _box(ax, 0.05, 0.72, 0.90, 0.16)
        ax.text(0.075, 0.85, "Banka profili", fontsize=14, fontweight="bold", color=TEXT, transform=ax.transAxes)
        ax.text(
            0.075,
            0.815,
            "Cari oran, stok/alacak devir hızı, net borç/FAVÖK ve Altman/Beneish gibi endüstriyel şirket oranları bankalara uygulanmadı.",
            fontsize=10,
            color=MUTED,
            transform=ax.transAxes,
            wrap=True,
        )
        ax.text(
            0.075,
            0.765,
            "Banka analizi kredi/mevduat, özkaynak/aktif, ROE/ROA, gelir-gider büyümesi ve F/K–PD/DD ekseninde tutulur.",
            fontsize=10,
            color=MUTED,
            transform=ax.transAxes,
            wrap=True,
        )
        left_y = 0.68
    else:
        left_y = 0.89
        right_y = 0.89
        for idx, group in enumerate(groups):
            if idx % 2 == 0:
                left_y = _draw_ratio_group(ax, group, 0.05, left_y, 0.43, 0.032)
            else:
                right_y = _draw_ratio_group(ax, group, 0.52, right_y, 0.43, 0.032)

    scores = financial.get("forensic_scores", {})
    groups_bottom = left_y if report.profile == "BANK" else min(left_y, right_y)
    score_h = 0.145
    score_bottom = max(0.040, groups_bottom - score_h - 0.022)
    _box(ax, 0.05, score_bottom, 0.90, score_h)
    ax.text(
        0.075,
        score_bottom + score_h - 0.022,
        "Skor Değerleri",
        fontsize=13,
        fontweight="bold",
        color=GREEN,
        transform=ax.transAxes,
        va="top",
    )
    labels = (
        ("altman_z", "Altman Z Skoru"),
        ("beneish_m", "Beneish M Skoru"),
        ("graham_number", "Graham"),
        ("piotroski_f", "Piotroski F Skor"),
        ("beta", "Beta"),
    )
    start_y = score_bottom + score_h - 0.050
    card_w = 0.166
    gap = 0.013
    for idx, (key, label) in enumerate(labels):
        x = 0.075 + idx * (card_w + gap)
        _box(ax, x, start_y - 0.078, card_w, 0.073)
        text, note, tone = _score_value(scores.get(key, {}), key)
        ax.text(
            x + 0.010,
            start_y - 0.012,
            label,
            fontsize=8.4,
            fontweight="bold",
            color=TEXT,
            transform=ax.transAxes,
            va="top",
        )
        ax.text(
            x + 0.010,
            start_y - 0.037,
            text,
            fontsize=13.0,
            fontweight="bold",
            color=tone,
            transform=ax.transAxes,
            va="top",
        )
        ax.text(
            x + 0.010,
            start_y - 0.058,
            note[:48],
            fontsize=5.9,
            color=MUTED,
            transform=ax.transAxes,
            va="top",
            wrap=True,
        )

    ax.text(
        0.05,
        0.012,
        str(financial.get("ratio_note", "Eksik veri oran/skor üretmez; veri yoksa alan boş bırakılır.")),
        fontsize=7.2,
        color=MUTED,
        transform=ax.transAxes,
        va="bottom",
    )
    fig.savefig(path, bbox_inches="tight", facecolor=BG)
    plt.close(fig)
    return path
