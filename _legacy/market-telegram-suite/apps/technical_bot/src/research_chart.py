"""16:9 integrated technical chart using the user-supplied Pine indicator logic."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import to_rgba
from matplotlib.patches import FancyBboxPatch, PathPatch, Rectangle
from matplotlib.path import Path as MplPath

from src.original_indicators import DivergencePoint, build_indicator_frame
from src.research_engine import ResearchReport, _prepare_prices

BG = "#070b12"
PANEL = "#0d131d"
PANEL_2 = "#111a27"
GRID = "#273142"
TEXT = "#eef4fb"
MUTED = "#8fa2b8"
GREEN = "#26a69a"
RED = "#ff5252"
AMBER = "#f2bd4a"
CYAN = "#49d6d0"

# Pine v6 built-in colours / explicit script colours.
PINE_BLUE = "#2196F3"
PINE_ORANGE = "#FF9800"
PINE_GREEN = "#4CAF50"
PINE_RED = "#F23645"
PINE_GRAY = "#787B86"
PINE_WHITE = "#FFFFFF"
PINE_YELLOW = "#FDD835"
RSI_PURPLE = "#7E57C2"
MACD_BLUE = "#2962FF"
MACD_ORANGE = "#FF6D00"
OBV_BLUE = "#2962FF"
ATR_RED = "#B71C1C"
ALPHA_BLUE = "#0022FC"
ALPHA_RED = "#FC0400"
ALPHA_GREEN = "#00E60F"
ALPHA_MAROON = "#80000B"


def _pct_change(values, periods: int) -> float | None:
    if len(values) <= periods:
        return None
    current = float(values.iloc[-1])
    previous = float(values.iloc[-1 - periods])
    return None if previous == 0 else (current / previous - 1.0) * 100.0


def _badge(ax: plt.Axes, x: float, title: str, value: str, tone: str = MUTED) -> None:
    ax.add_patch(
        FancyBboxPatch(
            (x, 0.17),
            0.145,
            0.62,
            boxstyle="round,pad=0.012,rounding_size=0.025",
            transform=ax.transAxes,
            facecolor=PANEL_2,
            edgecolor=GRID,
            linewidth=0.8,
        )
    )
    ax.text(x + 0.015, 0.61, title, transform=ax.transAxes, fontsize=7.2, color=MUTED, va="center")
    ax.text(x + 0.015, 0.36, value, transform=ax.transAxes, fontsize=9.5, color=tone, fontweight="bold", va="center")


def _candles(ax: plt.Axes, data) -> None:
    dates = mdates.date2num(data.index.to_pydatetime())
    width = 0.62
    for date, row in zip(dates, data.itertuples(), strict=False):
        open_price = float(row.Open)
        high = float(row.High)
        low = float(row.Low)
        close = float(row.Close)
        colour = GREEN if close >= open_price else RED
        ax.vlines(date, low, high, linewidth=0.70, color=colour, alpha=0.95, zorder=4)
        bottom = min(open_price, close)
        height = max(abs(close - open_price), max(abs(close) * 0.00045, 1e-6))
        ax.add_patch(
            Rectangle(
                (date - width / 2, bottom),
                width,
                height,
                facecolor=colour,
                edgecolor=colour,
                linewidth=0.50,
                zorder=5,
            )
        )


def _zone_label(zone, kind: str) -> str:
    level = f"{zone.midpoint:,.2f}" if abs(zone.high - zone.low) < 0.005 else f"{zone.low:,.2f}–{zone.high:,.2f}"
    role = "D" if kind == "destek" else "R"
    return f"{role} {level} · Q{zone.score:.0f} · {'+'.join(zone.sources[:3])}"


def _draw_zone(ax: plt.Axes, zone, kind: str, x_start, x_end) -> None:
    colour = GREEN if kind == "destek" else RED
    ax.fill_between(
        [x_start, x_end],
        [zone.low, zone.low],
        [zone.high, zone.high],
        color=colour,
        alpha=0.10,
        linewidth=0,
        zorder=1,
    )
    ax.hlines(zone.midpoint, x_start, x_end, colors=colour, linestyles="--", linewidth=0.75, alpha=0.8, zorder=2)
    ax.annotate(
        _zone_label(zone, kind),
        xy=(x_end, zone.midpoint),
        xytext=(6, 0),
        textcoords="offset points",
        fontsize=6.5,
        color=colour,
        va="center",
        ha="left",
        bbox={"boxstyle": "round,pad=0.18", "fc": PANEL_2, "ec": colour, "lw": 0.45, "alpha": 0.94},
        annotation_clip=False,
    )


def _style_panel(ax: plt.Axes, *, right_axis: bool = False) -> None:
    ax.set_facecolor(PANEL)
    ax.grid(True, color=GRID, alpha=0.30, linewidth=0.45)
    ax.tick_params(colors=MUTED, labelsize=6.3)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    if right_axis:
        ax.yaxis.tick_right()
        ax.tick_params(axis="y", labelleft=False, labelright=True)


def _panel_label(ax: plt.Axes, text: str) -> None:
    ax.text(0.005, 0.88, text, transform=ax.transAxes, fontsize=6.8, fontweight="bold", color=TEXT, va="top")


def _rgba(hex_colour: str, opacity: float) -> tuple[float, float, float, float]:
    red, green, blue, _ = to_rgba(hex_colour)
    return red, green, blue, opacity


def _gradient_between_curve_and_baseline(
    ax: plt.Axes,
    x,
    curve,
    *,
    baseline: float,
    y_bottom: float,
    y_top: float,
    bottom_rgba: tuple[float, float, float, float],
    top_rgba: tuple[float, float, float, float],
    zorder: float = 0.4,
) -> None:
    """Approximate Pine's gradient fill, clipped between a plot and baseline."""
    x_num = mdates.date2num(x.to_pydatetime())
    y = np.asarray(curve, dtype=float)
    finite = np.isfinite(y)
    if finite.sum() < 2:
        return
    x_num = x_num[finite]
    y = y[finite]
    vertices = np.column_stack([np.r_[x_num, x_num[::-1]], np.r_[y, np.full_like(y, baseline)[::-1]]])
    vertices = np.vstack([vertices, vertices[0]])
    codes = np.full(len(vertices), MplPath.LINETO, dtype=np.uint8)
    codes[0] = MplPath.MOVETO
    codes[-1] = MplPath.CLOSEPOLY
    patch = PathPatch(MplPath(vertices, codes), facecolor="none", edgecolor="none", transform=ax.transData)
    ax.add_patch(patch)

    rows = 256
    lower = np.array(bottom_rgba, dtype=float)
    upper = np.array(top_rgba, dtype=float)
    ramp = np.linspace(0.0, 1.0, rows)[:, None]
    rgba = lower[None, :] * (1.0 - ramp) + upper[None, :] * ramp
    image = np.repeat(rgba[:, None, :], 2, axis=1)
    artist = ax.imshow(
        image,
        extent=(float(x_num.min()), float(x_num.max()), y_bottom, y_top),
        origin="lower",
        aspect="auto",
        interpolation="bicubic",
        zorder=zorder,
    )
    artist.set_clip_path(patch)


def _draw_rsi_divergences(ax: plt.Axes, points: tuple[DivergencePoint, ...], start, end) -> None:
    for point in points:
        if point.index < start or point.index > end:
            continue
        bullish = "Bullish" in point.kind
        colour = PINE_GREEN if bullish else PINE_RED
        text = "Bull" if point.kind == "Regular Bullish" else "Bear" if point.kind == "Regular Bearish" else "H Bull" if bullish else "H Bear"

        if point.previous_index is not None and point.previous_rsi is not None:
            ax.plot(
                [point.previous_index, point.index],
                [point.previous_rsi, point.rsi],
                color=colour,
                linewidth=2.0,
                solid_capstyle="round",
                zorder=7,
            )
        ax.scatter([point.index], [point.rsi], s=16, color=colour, zorder=8)
        ax.annotate(
            f" {text} ",
            xy=(point.index, point.rsi),
            xytext=(0, -12 if bullish else 12),
            textcoords="offset points",
            fontsize=5.7,
            color=PINE_WHITE,
            ha="center",
            va="center",
            bbox={"boxstyle": "square,pad=0.10", "fc": colour, "ec": colour, "lw": 0.35},
            zorder=9,
        )


def render_research_chart(symbol: str, report: ResearchReport, output: Path) -> Path:
    """Render the Pine-faithful indicator stack in an exact 16:9 dashboard."""
    import borsapy as bp

    output.parent.mkdir(parents=True, exist_ok=True)
    raw = _prepare_prices(bp.Ticker(symbol).history(period="2y", interval="1d"))
    data, divergences = build_indicator_frame(raw, include_hidden_divergence=False)
    view = data.tail(150).copy()
    if view.empty:
        raise RuntimeError("No price bars available for research chart")

    plt.rcParams["font.family"] = "DejaVu Sans"
    figure = plt.figure(figsize=(16.0, 9.0), dpi=145, facecolor=BG)
    grid = figure.add_gridspec(
        8,
        1,
        height_ratios=[0.72, 3.25, 0.64, 0.86, 0.82, 0.95, 0.72, 0.72],
        hspace=0.035,
        left=0.045,
        right=0.925,
        top=0.975,
        bottom=0.065,
    )
    header_ax = figure.add_subplot(grid[0])
    price_ax = figure.add_subplot(grid[1])
    volume_ax = figure.add_subplot(grid[2], sharex=price_ax)
    macd_ax = figure.add_subplot(grid[3], sharex=price_ax)
    smi_ax = figure.add_subplot(grid[4], sharex=price_ax)
    rsi_ax = figure.add_subplot(grid[5], sharex=price_ax)
    obv_ax = figure.add_subplot(grid[6], sharex=price_ax)
    atr_ax = figure.add_subplot(grid[7], sharex=price_ax)

    header_ax.set_facecolor(PANEL)
    header_ax.axis("off")
    for current in (price_ax, volume_ax, macd_ax, smi_ax, rsi_ax, obv_ax, atr_ax):
        _style_panel(current, right_axis=True)

    price = float(view["Close"].iloc[-1])
    day = _pct_change(view["Close"], 1)
    week = _pct_change(view["Close"], 5)
    month = _pct_change(view["Close"], 21)
    structure = report.technical.get("structure", {})
    weekly = report.technical.get("weekly_structure", {})
    technical_score = report.technical.get("score")

    header_ax.text(0.010, 0.71, report.symbol, transform=header_ax.transAxes, fontsize=18, color=TEXT, fontweight="bold", va="center")
    header_ax.text(0.010, 0.34, f"{price:,.2f} TL", transform=header_ax.transAxes, fontsize=15, color=CYAN, fontweight="bold", va="center")
    header_ax.text(
        0.010,
        0.04,
        f"Günlük {structure.get('state', '—')} · Haftalık {weekly.get('state', '—')} · {structure.get('bos', 'Yeni BOS yok')}",
        transform=header_ax.transAxes,
        fontsize=7.2,
        color=MUTED,
        va="bottom",
    )
    _badge(header_ax, 0.24, "1 GÜN", "—" if day is None else f"{day:+.2f}%", GREEN if day is not None and day >= 0 else RED)
    _badge(header_ax, 0.40, "1 HAFTA", "—" if week is None else f"{week:+.2f}%", GREEN if week is not None and week >= 0 else RED)
    _badge(header_ax, 0.56, "1 AY", "—" if month is None else f"{month:+.2f}%", GREEN if month is not None and month >= 0 else RED)
    score_tone = GREEN if technical_score is not None and technical_score >= 70 else AMBER if technical_score is not None and technical_score >= 45 else RED
    _badge(header_ax, 0.72, "TEKNİK YAPI", "—" if technical_score is None else f"{technical_score:.0f}/100", score_tone)

    _candles(price_ax, view)
    price_ax.plot(view.index, view["BB_MID"], color="#aeb7c4", linewidth=0.70, alpha=0.75, label="BB Basis 20")
    price_ax.plot(view.index, view["BB_UPPER"], color="#6b7280", linewidth=0.60, alpha=0.75)
    price_ax.plot(view.index, view["BB_LOWER"], color="#6b7280", linewidth=0.60, alpha=0.75)
    price_ax.fill_between(view.index, view["BB_LOWER"].to_numpy(), view["BB_UPPER"].to_numpy(), color="#64748b", alpha=0.055, zorder=0)

    alpha = view["AlphaTrend"]
    alpha_lag2 = view["AlphaTrendLag2"]
    valid_alpha = alpha.notna() & alpha_lag2.notna()
    alpha_green = ((alpha > alpha_lag2) | ((alpha == alpha_lag2) & (alpha.shift(1) > alpha.shift(3)))).fillna(False)
    alpha_red = (valid_alpha & ~alpha_green).fillna(False)
    price_ax.fill_between(
        view.index,
        alpha.to_numpy(),
        alpha_lag2.to_numpy(),
        where=alpha_green.to_numpy() & valid_alpha.to_numpy(),
        color=ALPHA_GREEN,
        alpha=1.0,
        interpolate=True,
        zorder=2,
    )
    price_ax.fill_between(
        view.index,
        alpha.to_numpy(),
        alpha_lag2.to_numpy(),
        where=alpha_red.to_numpy(),
        color=ALPHA_MAROON,
        alpha=1.0,
        interpolate=True,
        zorder=2,
    )
    price_ax.plot(view.index, alpha, color=ALPHA_BLUE, linewidth=1.45, label="AlphaTrend", zorder=3)
    price_ax.plot(view.index, alpha_lag2, color=ALPHA_RED, linewidth=1.45, label="AlphaTrend[2]", zorder=3)

    x_start = mdates.date2num(view.index[0].to_pydatetime())
    x_end = mdates.date2num(view.index[-1].to_pydatetime())
    for zone in report.supports:
        _draw_zone(price_ax, zone, "destek", x_start, x_end)
    for zone in report.resistances:
        _draw_zone(price_ax, zone, "direnç", x_start, x_end)

    y_min = float(view["Low"].min())
    y_max = float(view["High"].max())
    span = max(y_max - y_min, 1e-6)
    view_start = view.index[0]
    if getattr(view_start, "tzinfo", None) is not None:
        view_start = view_start.tz_localize(None)
    for pivot in [item for item in report.technical.get("pivots", []) if item.get("time")][-11:]:
        try:
            pivot_time = np.datetime64(str(pivot["time"]).split("+")[0])
        except ValueError:
            continue
        if pivot_time < np.datetime64(view_start):
            continue
        pivot_price = float(pivot["price"])
        offset = span * (0.024 if pivot["type"] == "high" else -0.030)
        price_ax.text(
            pivot_time,
            pivot_price + offset,
            str(pivot["label"]),
            fontsize=6.1,
            fontweight="bold",
            color=TEXT,
            ha="center",
            va="center",
            bbox={"boxstyle": "round,pad=0.10", "fc": PANEL_2, "ec": GRID, "lw": 0.35, "alpha": 0.86},
            zorder=8,
        )

    bos = str(structure.get("bos", ""))
    if "BOS" in bos:
        level = None
        if "High" in bos and structure.get("last_high"):
            level = float(structure["last_high"]["price"])
        elif "Low" in bos and structure.get("last_low"):
            level = float(structure["last_low"]["price"])
        if level is not None:
            price_ax.axhline(level, linestyle=(0, (4, 4)), linewidth=0.8, color=AMBER, alpha=0.85)
            price_ax.text(
                view.index[int(len(view) * 0.58)],
                level,
                f" BOS · {level:,.2f}",
                fontsize=6.5,
                color=AMBER,
                va="bottom",
                bbox={"boxstyle": "round,pad=0.14", "fc": PANEL_2, "ec": AMBER, "lw": 0.35, "alpha": 0.90},
            )

    price_ax.axhline(price, linewidth=0.65, color=CYAN, alpha=0.35)
    price_ax.annotate(
        f" {price:,.2f}",
        xy=(x_end, price),
        xytext=(6, 0),
        textcoords="offset points",
        fontsize=6.8,
        color=TEXT,
        va="center",
        ha="left",
        bbox={"boxstyle": "round,pad=0.18", "fc": CYAN, "ec": CYAN, "lw": 0.45, "alpha": 0.82},
        annotation_clip=False,
    )
    price_ax.legend(loc="upper left", ncol=3, fontsize=6.2, frameon=False, labelcolor=TEXT)
    price_ax.set_xlim(view.index[0], view.index[-1] + np.timedelta64(12, "D"))
    _panel_label(price_ax, "FİYAT · BOLLINGER(20,2) · ALPHATREND(14,1)")

    volume_colours = [GREEN if close >= open_price else RED for open_price, close in zip(view["Open"], view["Close"], strict=False)]
    volume_ax.bar(view.index, view["Volume"], width=0.82, alpha=0.68, color=volume_colours)
    volume_ax.plot(view.index, view["Volume"].rolling(20).mean(), color=AMBER, linewidth=0.75, alpha=0.9)
    _panel_label(volume_ax, "HACİM · 20G ORT.")

    hist = view["MACD_HIST"]
    hist_prev = hist.shift(1)
    hist_colours = np.where(
        hist >= 0,
        np.where(hist > hist_prev, "#26A69A", "#B2DFDB"),
        np.where(hist > hist_prev, "#FFCDD2", "#FF5252"),
    )
    macd_ax.bar(view.index, hist, width=0.82, color=hist_colours, alpha=1.0)
    macd_ax.plot(view.index, view["MACD"], color=MACD_BLUE, linewidth=1.0)
    macd_ax.plot(view.index, view["MACD_SIGNAL"], color=MACD_ORANGE, linewidth=1.0)
    macd_ax.axhline(0, color="#787B8680", linewidth=0.65)
    _panel_label(macd_ax, "MACD · 12/26/9 EMA")

    # SMI Pine visuals: blue/orange lines, ±40 background, green/red gradients.
    smi_ax.fill_between(view.index, -40, 40, color=PINE_BLUE, alpha=0.10, zorder=0.2)
    _gradient_between_curve_and_baseline(
        smi_ax,
        view.index,
        view["SMI"],
        baseline=0.0,
        y_bottom=40.0,
        y_top=120.0,
        bottom_rgba=_rgba(PINE_GREEN, 0.0),
        top_rgba=_rgba("#4CAF4F", 0.50),
    )
    _gradient_between_curve_and_baseline(
        smi_ax,
        view.index,
        view["SMI"],
        baseline=0.0,
        y_bottom=-120.0,
        y_top=-40.0,
        bottom_rgba=_rgba(PINE_RED, 0.50),
        top_rgba=_rgba(PINE_RED, 0.0),
    )
    smi_ax.plot(view.index, view["SMI"], color=PINE_BLUE, linewidth=1.0, zorder=4)
    smi_ax.plot(view.index, view["SMI_SIGNAL"], color=PINE_ORANGE, linewidth=1.0, zorder=4)
    smi_ax.axhline(40, color=PINE_GRAY, linewidth=0.60)
    smi_ax.axhline(-40, color=PINE_GRAY, linewidth=0.60)
    smi_ax.axhline(0, color=PINE_GRAY, linewidth=0.50, alpha=0.50)
    smi_ax.set_ylim(-120, 120)
    _panel_label(smi_ax, "SMI · 10/3/3 · ORİJİNAL GRADIENT")

    # Standard TradingView RSI supplied by the user, with divergence enabled.
    rsi_ax.fill_between(view.index, 30, 70, color=RSI_PURPLE, alpha=0.10, zorder=0.2)
    _gradient_between_curve_and_baseline(
        rsi_ax,
        view.index,
        view["RSI14"],
        baseline=50.0,
        y_bottom=70.0,
        y_top=100.0,
        bottom_rgba=_rgba(PINE_GREEN, 0.0),
        top_rgba=_rgba(PINE_GREEN, 1.0),
    )
    _gradient_between_curve_and_baseline(
        rsi_ax,
        view.index,
        view["RSI14"],
        baseline=50.0,
        y_bottom=0.0,
        y_top=30.0,
        bottom_rgba=_rgba(PINE_RED, 1.0),
        top_rgba=_rgba(PINE_RED, 0.0),
    )
    rsi_ax.plot(view.index, view["RSI14"], color=RSI_PURPLE, linewidth=1.15, zorder=4)
    rsi_ax.plot(view.index, view["RSI_MA14"], color=PINE_YELLOW, linewidth=0.90, zorder=4)
    rsi_ax.axhline(70, color=PINE_GRAY, linewidth=0.60)
    rsi_ax.axhline(50, color=PINE_GRAY, linewidth=0.55, alpha=0.50)
    rsi_ax.axhline(30, color=PINE_GRAY, linewidth=0.60)
    rsi_ax.set_ylim(0, 100)
    _draw_rsi_divergences(rsi_ax, divergences, view.index[0], view.index[-1])
    _panel_label(rsi_ax, "RSI · 14 · SMA14 · REGULAR DIVERGENCE AÇIK (5/5, 5–60)")

    obv_ax.plot(view.index, view["OBV"], color=OBV_BLUE, linewidth=1.0)
    _panel_label(obv_ax, "OBV · ORİJİNAL KÜMÜLATİF")

    atr_ax.plot(view.index, view["ATR14"], color=ATR_RED, linewidth=1.0)
    _panel_label(atr_ax, "ATR · 14 RMA")
    atr_ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=7, maxticks=10))
    atr_ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m.%y"))

    for current in (price_ax, volume_ax, macd_ax, smi_ax, rsi_ax, obv_ax):
        plt.setp(current.get_xticklabels(), visible=False)

    figure.text(
        0.012,
        0.015,
        "Pine eşleşmesi: RSI/SMI/MACD/OBV/ATR/AlphaTrend kullanıcı kodları · RSI regular divergence açık",
        fontsize=6.2,
        color=MUTED,
        ha="left",
    )
    figure.text(
        0.988,
        0.015,
        "AlphaTrend BUY/SELL etiketleri önceki tercih gereği bastırılır · otomatik AL/SAT değildir",
        fontsize=6.2,
        color=MUTED,
        ha="right",
    )
    figure.savefig(output, facecolor=BG, dpi=145)
    plt.close(figure)
    return output
