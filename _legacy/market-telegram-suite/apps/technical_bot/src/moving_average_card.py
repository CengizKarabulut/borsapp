"""Daily moving-average table for research reports.

The card intentionally keeps all nine averages off the price chart. It shows
5/8/13, 21/34/55 and 89/144/233 daily simple moving averages with current value,
price relation, local slope and one summary line per horizon. Recently listed
shares are not rejected: unavailable long averages are shown as data missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from src.original_indicators import moving_averages
from src.research_engine import _prepare_prices

BG = "#0b1220"
PANEL = "#111a2b"
GRID = "#223047"
TEXT = "#eef4fb"
MUTED = "#8fa2b8"
GREEN = "#39c98a"
RED = "#ff6577"
AMBER = "#f2bd4a"
CYAN = "#49d6d0"

GROUPS = (
    ("KISA VADE", (5, 8, 13)),
    ("ORTA VADE", (21, 34, 55)),
    ("UZUN VADE", (89, 144, 233)),
)


def _trend(series) -> str:
    clean = series.dropna()
    if len(clean) < 4:
        return "—"
    now = float(clean.iloc[-1])
    previous = float(clean.iloc[-4])
    if previous == 0:
        return "—"
    change = (now / previous - 1.0) * 100.0
    if change > 0.15:
        return "YUKARI"
    if change < -0.15:
        return "AŞAĞI"
    return "YATAY"


def _group_summary(price: float, values: list[float | None]) -> str:
    if len(values) != 3 or any(value is None for value in values):
        return "VERİ YETERSİZ"
    first, second, third = (float(value) for value in values)
    if price > first > second > third:
        return "POZİTİF DİZİLİM"
    if price < first < second < third:
        return "NEGATİF DİZİLİM"
    return "KARIŞIK DİZİLİM"


def build_moving_average_snapshot(symbol: str) -> dict[str, Any]:
    import borsapy as bp

    ticker = symbol.strip().upper().removesuffix(".IS")
    frame = _prepare_prices(bp.Ticker(ticker).history(period="2y", interval="1d"))
    if frame.empty or len(frame) < 20:
        raise RuntimeError(f"{ticker}: MA tablosu için yeterli günlük geçmiş yok")
    ma = moving_averages(frame)
    price = float(frame["Close"].iloc[-1])
    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, str]] = []

    for group_name, periods in GROUPS:
        group_values: list[float | None] = []
        for period in periods:
            column = f"MA{period}"
            value = float(ma[column].iloc[-1]) if np.isfinite(ma[column].iloc[-1]) else None
            group_values.append(value)
            relation = "—" if value is None else "FİYAT ÜSTÜNDE" if price > value else "FİYAT ALTINDA"
            rows.append(
                {
                    "group": group_name,
                    "period": period,
                    "value": value,
                    "relation": relation,
                    "trend": _trend(ma[column]),
                }
            )
        summaries.append({"group": group_name, "summary": _group_summary(price, group_values)})

    return {
        "symbol": ticker,
        "price": price,
        "history_bars": len(frame),
        "rows": rows,
        "summaries": summaries,
    }


def _tone(value: str) -> str:
    if "POZİTİF" in value or value == "YUKARI" or value == "FİYAT ÜSTÜNDE":
        return GREEN
    if "NEGATİF" in value or value == "AŞAĞI" or value == "FİYAT ALTINDA":
        return RED
    return AMBER if "KARIŞIK" in value or value == "YATAY" else MUTED


def render_moving_average_card(symbol: str, output: Path) -> tuple[Path, dict[str, Any]]:
    snapshot = build_moving_average_snapshot(symbol)
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = "DejaVu Sans"
    fig = plt.figure(figsize=(9.0, 11.0), dpi=135, facecolor=BG)
    ax = fig.add_axes([0.055, 0.06, 0.89, 0.86])
    ax.set_facecolor(PANEL)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    fig.text(0.06, 0.955, f"{snapshot['symbol']} · HAREKETLİ ORTALAMALAR", color=TEXT, fontsize=18, fontweight="bold", va="top")
    fig.text(
        0.06,
        0.925,
        f"Günlük SMA · Son fiyat {snapshot['price']:,.2f} TL · {snapshot['history_bars']} günlük bar",
        color=MUTED,
        fontsize=9.5,
        va="top",
    )

    headers = ((0.04, "VADE"), (0.25, "MA"), (0.38, "DEĞER"), (0.58, "FİYATA GÖRE"), (0.82, "EĞİLİM"))
    for x, text in headers:
        ax.text(x, 0.95, text, color=MUTED, fontsize=8.8, fontweight="bold", va="center")
    ax.plot([0.03, 0.97], [0.925, 0.925], color=GRID, linewidth=0.9)

    y = 0.865
    gap = 0.078
    for row in snapshot["rows"]:
        ax.text(0.04, y, row["group"], color=MUTED, fontsize=8.5, va="center")
        ax.text(0.25, y, f"MA{row['period']}", color=TEXT, fontsize=10.0, fontweight="bold", va="center")
        value_text = "VERİ YETERSİZ" if row["value"] is None else f"{row['value']:,.2f}"
        ax.text(0.38, y, value_text, color=CYAN if row["value"] is not None else MUTED, fontsize=9.2, va="center")
        ax.text(0.58, y, row["relation"], color=_tone(row["relation"]), fontsize=8.5, va="center")
        ax.text(0.82, y, row["trend"], color=_tone(row["trend"]), fontsize=8.8, fontweight="bold", va="center")
        ax.plot([0.03, 0.97], [y - 0.035, y - 0.035], color=GRID, linewidth=0.45, alpha=0.75)
        y -= gap

    ax.text(0.04, 0.165, "ÖZET DİZİLİM", color=TEXT, fontsize=10.5, fontweight="bold")
    summary_y = 0.115
    for item in snapshot["summaries"]:
        ax.text(0.04, summary_y, item["group"], color=MUTED, fontsize=8.8, va="center")
        ax.text(0.28, summary_y, item["summary"], color=_tone(item["summary"]), fontsize=9.5, fontweight="bold", va="center")
        summary_y -= 0.045

    fig.text(
        0.94,
        0.025,
        "Değer + fiyat konumu + 3 günlük MA eğimi · eksik uzun geçmiş uydurulmaz · otomatik AL/SAT değildir",
        color=MUTED,
        fontsize=7.7,
        ha="right",
    )
    fig.savefig(output, facecolor=BG, bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)
    return output, snapshot
