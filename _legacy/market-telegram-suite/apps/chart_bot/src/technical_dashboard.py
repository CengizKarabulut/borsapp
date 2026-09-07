"""Tek sayfalik, gösterge odakli /grafik dashboard'u.

Eski 2x2 eşit fiyat grafiği ızgarasının yerine tek bir büyük fiyat/trend alanı
ve üç yardımcı gösterge sütunu üretir. Amaç ham indikatör yığını değil;
trend, momentum, para akışı ve volatiliteyi aynı bakışta okunabilir kılmaktır.

Ana panel:
- Mumlar
- Bollinger 20/2
- AlphaTrend 14/1 (hacim varsa MFI dalı)
- EMA 8/21/55
- teyitli HH/HL/LH/LL pivotları ve BOS işaretleri
- en yakın teyitli swing destek/direnci
- hacim + 20 bar ortalama

Alt bloklar:
- MACD + SMI
- RSI (+ düzenli uyumsuzluk noktaları) + OBV
- ATR% + RVOL + ADX/DMI

Otomatik AL/SAT etiketi üretmez.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

from . import indicators as ind
from . import telegram as tg
from .data_sources import fetch_ohlcv
from .pipeline import DEFAULT_PERIODS, INTERVAL_LABELS, default_bars, last_bar_is_open

# Beyaz zeminli araştırma görselleriyle aynı görsel dil.
BG = "#FFFFFF"
PANEL = "#FFFFFF"
GRID = "#E5E7EB"
TEXT = "#111827"
MUTED = "#6B7280"
UP = "#15803D"
DOWN = "#DC2626"
BLUE = "#2563EB"
NAVY = "#1E3A8A"
AMBER = "#D97706"
PURPLE = "#7C3AED"
CYAN = "#0891B2"
SLATE = "#64748B"
SOFT_BLUE = "#DBEAFE"


@dataclass(frozen=True)
class DashboardResult:
    path: Path
    symbol: str
    interval: str
    subtitle: str
    snapshot: list[tuple[str, str, str]]


def _last(series: pd.Series) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    return float(clean.iloc[-1]) if len(clean) else float("nan")


def _fmt(value: float, digits: int = 2) -> str:
    if not np.isfinite(value):
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ")


def _money_flow_index(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    high = pd.to_numeric(frame["High"], errors="coerce").astype(float)
    low = pd.to_numeric(frame["Low"], errors="coerce").astype(float)
    close = pd.to_numeric(frame["Close"], errors="coerce").astype(float)
    volume = pd.to_numeric(frame["Volume"], errors="coerce").fillna(0.0).astype(float)
    typical = (high + low + close) / 3.0
    raw_flow = typical * volume
    delta = typical.diff()
    positive = raw_flow.where(delta > 0.0, 0.0)
    negative = raw_flow.where(delta < 0.0, 0.0)
    pos_sum = positive.rolling(length, min_periods=length).sum()
    neg_sum = negative.rolling(length, min_periods=length).sum()
    ratio = pos_sum / neg_sum.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + ratio)
    result = result.where(neg_sum != 0.0, 100.0)
    return result.where(pos_sum != 0.0, 0.0)


def _alpha_trend(
    frame: pd.DataFrame,
    period: int = 14,
    multiplier: float = 1.0,
) -> pd.DataFrame:
    """KivancOzbilgic AlphaTrend 14/1; AL/SAT etiketleri bilinçli olarak yok."""
    tr = ind.true_range(frame)
    atr_sma = tr.rolling(period, min_periods=period).mean()
    low = pd.to_numeric(frame["Low"], errors="coerce").astype(float)
    high = pd.to_numeric(frame["High"], errors="coerce").astype(float)
    up_t = low - atr_sma * multiplier
    down_t = high + atr_sma * multiplier

    volume = pd.to_numeric(frame["Volume"], errors="coerce").fillna(0.0)
    if float(volume.abs().sum()) > 0:
        condition = _money_flow_index(frame, period) >= 50.0
    else:
        condition = ind.rsi(frame, period)["RSI"] >= 50.0

    values = pd.Series(np.nan, index=frame.index, dtype=float)
    previous = 0.0
    for i in range(len(frame)):
        if not np.isfinite(up_t.iloc[i]) or not np.isfinite(down_t.iloc[i]):
            continue
        if bool(condition.iloc[i]):
            current = previous if up_t.iloc[i] < previous else float(up_t.iloc[i])
        else:
            current = previous if down_t.iloc[i] > previous else float(down_t.iloc[i])
        values.iloc[i] = current
        previous = current

    lag2 = values.shift(2)
    direction = pd.Series(
        np.where(values >= lag2, 1.0, -1.0), index=frame.index, dtype=float
    ).where(values.notna() & lag2.notna())
    return pd.DataFrame({"AlphaTrend": values, "AlphaTrendLag2": lag2, "AlphaTrendDir": direction})


def _pivot_positions(values: pd.Series, left: int, right: int, mode: str) -> list[int]:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    out: list[int] = []
    for i in range(left, len(arr) - right):
        window = arr[i - left : i + right + 1]
        if not np.isfinite(window).all():
            continue
        center = arr[i]
        if mode == "high":
            ok = center == np.max(window) and int(np.sum(window == center)) == 1
        else:
            ok = center == np.min(window) and int(np.sum(window == center)) == 1
        if ok:
            out.append(i)
    return out


def _market_structure(frame: pd.DataFrame, left: int = 3, right: int = 3) -> dict:
    """Teyitli swing yapısı: HH/HL/LH/LL ve teyitten sonra oluşan BOS."""
    highs = _pivot_positions(frame["High"], left, right, "high")
    lows = _pivot_positions(frame["Low"], left, right, "low")

    high_labels: list[tuple[int, float, str]] = []
    low_labels: list[tuple[int, float, str]] = []
    prev_high: float | None = None
    prev_low: float | None = None

    for i in highs:
        value = float(frame["High"].iloc[i])
        label = "SH" if prev_high is None else ("HH" if value > prev_high else "LH")
        high_labels.append((i, value, label))
        prev_high = value
    for i in lows:
        value = float(frame["Low"].iloc[i])
        label = "SL" if prev_low is None else ("HL" if value > prev_low else "LL")
        low_labels.append((i, value, label))
        prev_low = value

    confirmations: dict[int, list[tuple[str, int, float]]] = {}
    for i, value, _ in high_labels:
        confirmations.setdefault(i + right, []).append(("high", i, value))
    for i, value, _ in low_labels:
        confirmations.setdefault(i + right, []).append(("low", i, value))

    close = pd.to_numeric(frame["Close"], errors="coerce").to_numpy(dtype=float)
    active_high: tuple[int, float] | None = None
    active_low: tuple[int, float] | None = None
    broken_high: int | None = None
    broken_low: int | None = None
    bos: list[tuple[int, float, str]] = []

    for j in range(len(frame)):
        for kind, pivot_i, level in confirmations.get(j, []):
            if kind == "high":
                active_high = (pivot_i, level)
                broken_high = None
            else:
                active_low = (pivot_i, level)
                broken_low = None
        if j == 0 or not np.isfinite(close[j]) or not np.isfinite(close[j - 1]):
            continue
        if active_high and broken_high != active_high[0]:
            level = active_high[1]
            if close[j - 1] <= level < close[j]:
                bos.append((j, close[j], "BOS↑"))
                broken_high = active_high[0]
        if active_low and broken_low != active_low[0]:
            level = active_low[1]
            if close[j - 1] >= level > close[j]:
                bos.append((j, close[j], "BOS↓"))
                broken_low = active_low[0]

    current = float(frame["Close"].iloc[-1])
    confirmed_highs = [(i, v, lab) for i, v, lab in high_labels if i + right < len(frame)]
    confirmed_lows = [(i, v, lab) for i, v, lab in low_labels if i + right < len(frame)]
    supports = [(i, v, lab) for i, v, lab in confirmed_lows if v < current]
    resistances = [(i, v, lab) for i, v, lab in confirmed_highs if v > current]
    support = max(supports, key=lambda item: item[1]) if supports else None
    resistance = min(resistances, key=lambda item: item[1]) if resistances else None
    return {
        "highs": high_labels,
        "lows": low_labels,
        "bos": bos,
        "support": support,
        "resistance": resistance,
    }


def _style_axis(ax, *, right: bool = True) -> None:
    ax.set_facecolor(PANEL)
    ax.grid(True, color=GRID, linewidth=0.65, alpha=0.8)
    for spine in ax.spines.values():
        spine.set_color(GRID)
    ax.tick_params(axis="both", labelsize=8, colors=MUTED, length=0)
    if right:
        ax.yaxis.tick_right()
        ax.yaxis.set_label_position("right")


def _draw_candles(ax, frame: pd.DataFrame) -> None:
    opens = frame["Open"].to_numpy(dtype=float)
    highs = frame["High"].to_numpy(dtype=float)
    lows = frame["Low"].to_numpy(dtype=float)
    closes = frame["Close"].to_numpy(dtype=float)
    for x, (o, h, lo, c) in enumerate(zip(opens, highs, lows, closes)):
        if not all(np.isfinite([o, h, lo, c])):
            continue
        color = UP if c >= o else DOWN
        ax.vlines(x, lo, h, color=color, linewidth=0.8, zorder=3)
        bottom = min(o, c)
        height = abs(c - o)
        if height == 0:
            height = max((h - lo) * 0.015, abs(c) * 1e-4)
        ax.add_patch(Rectangle((x - 0.31, bottom), 0.62, height,
                               facecolor=color, edgecolor=color, linewidth=0.4, zorder=4))


def _x_ticks(ax, index: pd.DatetimeIndex, interval: str, count: int = 7) -> None:
    if len(index) == 0:
        return
    positions = np.unique(np.linspace(0, len(index) - 1, min(count, len(index)), dtype=int))
    if interval in {"1m", "5m", "15m", "30m", "1h", "2h", "3h", "4h"}:
        labels = [index[i].strftime("%d.%m\n%H:%M") for i in positions]
    elif interval == "1mo":
        labels = [index[i].strftime("%m.%Y") for i in positions]
    else:
        labels = [index[i].strftime("%d.%m.%y") for i in positions]
    ax.set_xticks(positions)
    ax.set_xticklabels(labels, fontsize=7, color=MUTED)


def _panel_title(ax, title: str, detail: str = "") -> None:
    ax.text(0.01, 0.96, title, transform=ax.transAxes, va="top", ha="left",
            fontsize=9.5, fontweight="bold", color=TEXT)
    if detail:
        ax.text(0.99, 0.96, detail, transform=ax.transAxes, va="top", ha="right",
                fontsize=7.5, color=MUTED)


def _scaled_obv(series: pd.Series) -> tuple[pd.Series, str, float]:
    peak = float(pd.to_numeric(series, errors="coerce").abs().max()) if len(series) else 0.0
    if peak >= 1_000_000_000:
        return series / 1_000_000_000.0, "mr", 1_000_000_000.0
    if peak >= 1_000_000:
        return series / 1_000_000.0, "mn", 1_000_000.0
    if peak >= 1_000:
        return series / 1_000.0, "bin", 1_000.0
    return series, "", 1.0


def render_dashboard(
    frame: pd.DataFrame,
    path: str | Path,
    *,
    symbol: str,
    interval: str,
    subtitle: str,
    last_bar_open: bool = False,
) -> list[tuple[str, str, str]]:
    """Hazır OHLCV verisinden beyaz temalı teknik dashboard üretir."""
    if len(frame) < 60:
        raise ValueError("Dashboard için en az 60 bar gerekli")

    frame = frame.copy()
    bb = ind.bollinger(frame, 20, 2.0)
    ma = ind.moving_averages(frame, specs=(("ema", 8), ("ema", 21), ("ema", 55)))
    macd = ind.macd(frame, 12, 26, 9)
    smi = ind.stochastic_momentum_index(frame, 10, 3, 3)
    rsi = ind.rsi(frame, 14, 14)
    obv = ind.obv(frame, 14)
    atr = ind.atr_bands(frame, 14)
    volume = ind.volume_bars(frame, 20)
    adx = ind.adx_dmi(frame, 14, 14)
    alpha = _alpha_trend(frame, 14, 1.0)
    structure = _market_structure(frame)

    x = np.arange(len(frame))
    fig = plt.figure(figsize=(19.2, 13.2), dpi=150, facecolor=BG)
    outer = fig.add_gridspec(2, 3, height_ratios=[3.35, 2.20], hspace=0.18, wspace=0.13)
    top = outer[0, :].subgridspec(2, 1, height_ratios=[4.6, 1.0], hspace=0.035)
    ax_price = fig.add_subplot(top[0])
    ax_vol = fig.add_subplot(top[1], sharex=ax_price)

    left = outer[1, 0].subgridspec(2, 1, hspace=0.13)
    ax_macd = fig.add_subplot(left[0])
    ax_smi = fig.add_subplot(left[1], sharex=ax_macd)

    middle = outer[1, 1].subgridspec(2, 1, hspace=0.13)
    ax_rsi = fig.add_subplot(middle[0])
    ax_obv = fig.add_subplot(middle[1], sharex=ax_rsi)

    right = outer[1, 2].subgridspec(3, 1, hspace=0.16)
    ax_atr = fig.add_subplot(right[0])
    ax_rvol = fig.add_subplot(right[1], sharex=ax_atr)
    ax_adx = fig.add_subplot(right[2], sharex=ax_atr)

    for ax in (ax_price, ax_vol, ax_macd, ax_smi, ax_rsi, ax_obv, ax_atr, ax_rvol, ax_adx):
        _style_axis(ax)

    # --- Ana fiyat / trend paneli -------------------------------------------------
    _draw_candles(ax_price, frame)
    ax_price.fill_between(x, bb["BB_lower"].to_numpy(), bb["BB_upper"].to_numpy(),
                          color=SOFT_BLUE, alpha=0.34, linewidth=0, zorder=0)
    ax_price.plot(x, bb["BB_upper"], color=SLATE, linewidth=0.9, linestyle="--", label="BB üst")
    ax_price.plot(x, bb["BB_mid"], color=SLATE, linewidth=0.8, linestyle=":", label="BB20")
    ax_price.plot(x, bb["BB_lower"], color=SLATE, linewidth=0.9, linestyle="--", label="BB alt")

    ax_price.plot(x, ma["EMA8"], color=AMBER, linewidth=1.0, label="EMA8")
    ax_price.plot(x, ma["EMA21"], color=BLUE, linewidth=1.15, label="EMA21")
    ax_price.plot(x, ma["EMA55"], color=PURPLE, linewidth=1.25, label="EMA55")

    alpha_up = alpha["AlphaTrend"].where(alpha["AlphaTrendDir"] > 0)
    alpha_down = alpha["AlphaTrend"].where(alpha["AlphaTrendDir"] < 0)
    ax_price.plot(x, alpha_up, color=UP, linewidth=2.0, label="AlphaTrend↑", zorder=5)
    ax_price.plot(x, alpha_down, color=DOWN, linewidth=2.0, label="AlphaTrend↓", zorder=5)
    ax_price.plot(x, alpha["AlphaTrendLag2"], color=NAVY, linewidth=0.75,
                  linestyle=":", alpha=0.70, label="AlphaTrend lag2")

    # Son pivot etiketleri; tüm geçmişi yazıp grafiği boğma.
    all_pivots = sorted(
        [(i, v, lab, "high") for i, v, lab in structure["highs"]]
        + [(i, v, lab, "low") for i, v, lab in structure["lows"]],
        key=lambda item: item[0],
    )[-16:]
    for i, value, label, kind in all_pivots:
        color = DOWN if kind == "high" else UP
        offset = 9 if kind == "high" else -13
        ax_price.annotate(label, (i, value), xytext=(0, offset), textcoords="offset points",
                          ha="center", va="center", fontsize=7.5, fontweight="bold",
                          color=color, zorder=7)
    for i, value, label in structure["bos"][-8:]:
        color = UP if "↑" in label else DOWN
        ax_price.annotate(label, (i, value), xytext=(0, 13 if "↑" in label else -15),
                          textcoords="offset points", ha="center", fontsize=7.2,
                          fontweight="bold", color=color,
                          bbox=dict(boxstyle="round,pad=0.18", fc=BG, ec=color, lw=0.7), zorder=8)

    support = structure["support"]
    resistance = structure["resistance"]
    if support:
        ax_price.axhline(support[1], color=UP, linestyle="--", linewidth=0.9, alpha=0.8)
        ax_price.text(len(frame) - 1, support[1], f"  Destek {support[1]:.2f}",
                      color=UP, fontsize=7.5, va="bottom", ha="right")
    if resistance:
        ax_price.axhline(resistance[1], color=DOWN, linestyle="--", linewidth=0.9, alpha=0.8)
        ax_price.text(len(frame) - 1, resistance[1], f"  Direnç {resistance[1]:.2f}",
                      color=DOWN, fontsize=7.5, va="top", ha="right")

    current = float(frame["Close"].iloc[-1])
    ax_price.axhline(current, color=TEXT, linewidth=0.7, alpha=0.45)
    _panel_title(ax_price, "FİYAT · TREND · PİYASA YAPISI",
                 "BB20/2 · AlphaTrend14/1 · EMA8/21/55 · teyitli swing/BOS")
    ax_price.legend(loc="lower left", ncol=7, fontsize=6.8, frameon=False,
                    labelcolor=TEXT, handlelength=2.1)
    ax_price.set_xlim(-1, len(frame) + 1)
    plt.setp(ax_price.get_xticklabels(), visible=False)

    # Hacim
    colors = np.where(frame["Close"].to_numpy() >= frame["Open"].to_numpy(), UP, DOWN)
    ax_vol.bar(x, volume["VOL"], color=colors, width=0.72, alpha=0.72)
    ax_vol.plot(x, volume["VOL_ma"], color=AMBER, linewidth=1.0)
    _panel_title(ax_vol, "HACİM", "20 bar ortalama")
    _x_ticks(ax_vol, frame.index, interval)

    # --- Momentum ----------------------------------------------------------------
    hist = macd["MACD_hist"]
    hist_colors = np.where(hist >= 0, UP, DOWN)
    ax_macd.bar(x, hist, color=hist_colors, width=0.72, alpha=0.70)
    ax_macd.plot(x, macd["MACD"], color=BLUE, linewidth=1.05)
    ax_macd.plot(x, macd["MACD_signal"], color=AMBER, linewidth=1.0)
    ax_macd.axhline(0, color=SLATE, linewidth=0.7)
    _panel_title(ax_macd, "MACD", "12/26/9")
    plt.setp(ax_macd.get_xticklabels(), visible=False)

    ax_smi.plot(x, smi["SMI"], color=BLUE, linewidth=1.1)
    ax_smi.plot(x, smi["SMI_signal"], color=AMBER, linewidth=1.0)
    ax_smi.axhline(40, color=DOWN, linestyle="--", linewidth=0.7)
    ax_smi.axhline(-40, color=UP, linestyle="--", linewidth=0.7)
    ax_smi.axhline(0, color=SLATE, linewidth=0.6)
    ax_smi.set_ylim(-120, 120)
    _panel_title(ax_smi, "SMI", "10/3/3 · ±40")
    _x_ticks(ax_smi, frame.index, interval, count=5)

    # --- Güç / para akışı ---------------------------------------------------------
    ax_rsi.plot(x, rsi["RSI"], color=BLUE, linewidth=1.1)
    ax_rsi.plot(x, rsi["RSI_ma"], color=AMBER, linewidth=0.95)
    ax_rsi.axhline(70, color=DOWN, linestyle="--", linewidth=0.7)
    ax_rsi.axhline(50, color=SLATE, linestyle=":", linewidth=0.6)
    ax_rsi.axhline(30, color=UP, linestyle="--", linewidth=0.7)
    bull = rsi.get("RSI_div_bull_points")
    bear = rsi.get("RSI_div_bear_points")
    if bull is not None:
        idx = np.flatnonzero(np.isfinite(bull.to_numpy(dtype=float)))
        ax_rsi.scatter(idx, bull.iloc[idx], s=24, color=UP, marker="^", zorder=5)
    if bear is not None:
        idx = np.flatnonzero(np.isfinite(bear.to_numpy(dtype=float)))
        ax_rsi.scatter(idx, bear.iloc[idx], s=24, color=DOWN, marker="v", zorder=5)
    ax_rsi.set_ylim(0, 100)
    _panel_title(ax_rsi, "RSI", "14 + SMA14 · düzenli uyumsuzluk")
    plt.setp(ax_rsi.get_xticklabels(), visible=False)

    obv_line, unit, divisor = _scaled_obv(obv["OBV"])
    ax_obv.plot(x, obv_line, color=CYAN, linewidth=1.1)
    ax_obv.plot(x, obv["OBV_ma"] / divisor, color=AMBER, linewidth=0.9)
    _panel_title(ax_obv, "OBV" + (f" ({unit})" if unit else ""), "SMA14")
    _x_ticks(ax_obv, frame.index, interval, count=5)

    # --- Risk / volatilite / hacim gücü -----------------------------------------
    ax_atr.plot(x, atr["ATR_pct"], color=DOWN, linewidth=1.1)
    _panel_title(ax_atr, "ATR / FİYAT", "14 · %")
    plt.setp(ax_atr.get_xticklabels(), visible=False)

    rvol = volume["RVOL"]
    rv_colors = np.where(rvol >= 1.5, CYAN, SLATE)
    ax_rvol.bar(x, rvol, color=rv_colors, width=0.72, alpha=0.75)
    ax_rvol.axhline(1.0, color=SLATE, linestyle="--", linewidth=0.7)
    ax_rvol.axhline(2.0, color=DOWN, linestyle="--", linewidth=0.7)
    finite_rv = pd.to_numeric(rvol, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
    if len(finite_rv):
        ax_rvol.set_ylim(0, max(3.0, float(finite_rv.quantile(0.98)) * 1.15))
    _panel_title(ax_rvol, "RVOL", "20 bar · 1x/2x")
    plt.setp(ax_rvol.get_xticklabels(), visible=False)

    ax_adx.plot(x, adx["ADX"], color=PURPLE, linewidth=1.15)
    ax_adx.plot(x, adx["DI_plus"], color=UP, linewidth=0.85)
    ax_adx.plot(x, adx["DI_minus"], color=DOWN, linewidth=0.85)
    ax_adx.axhline(25, color=SLATE, linestyle="--", linewidth=0.7)
    _panel_title(ax_adx, "ADX / DMI", "14 · 25 trend eşiği")
    _x_ticks(ax_adx, frame.index, interval, count=5)

    # --- Başlık ve özet -----------------------------------------------------------
    previous = float(frame["Close"].iloc[-2])
    change = (current / previous - 1.0) * 100.0 if previous else 0.0
    at_value = _last(alpha["AlphaTrend"])
    at_lag = _last(alpha["AlphaTrendLag2"])
    ema8, ema21, ema55 = (_last(ma["EMA8"]), _last(ma["EMA21"]), _last(ma["EMA55"]))
    macd_hist = _last(hist)
    smi_value = _last(smi["SMI"])
    smi_signal = _last(smi["SMI_signal"])
    rsi_value = _last(rsi["RSI"])
    rvol_value = _last(rvol)
    atr_pct = _last(atr["ATR_pct"])
    adx_value = _last(adx["ADX"])

    trend_positive = (
        np.isfinite(at_value) and np.isfinite(at_lag) and at_value >= at_lag
        and np.isfinite(ema8) and np.isfinite(ema21) and np.isfinite(ema55)
        and ema8 >= ema21 >= ema55
    )
    trend_negative = (
        np.isfinite(at_value) and np.isfinite(at_lag) and at_value < at_lag
        and np.isfinite(ema8) and np.isfinite(ema21) and np.isfinite(ema55)
        and ema8 <= ema21 <= ema55
    )
    trend_text = "Pozitif" if trend_positive else "Negatif" if trend_negative else "Karışık"
    momentum_positive = macd_hist >= 0 and smi_value >= smi_signal
    momentum_negative = macd_hist < 0 and smi_value < smi_signal
    momentum_text = "Pozitif" if momentum_positive else "Negatif" if momentum_negative else "Karışık"

    fig.suptitle(
        f"{symbol} · {INTERVAL_LABELS.get(interval, interval)} TEKNİK DASHBOARD",
        x=0.035, y=0.982, ha="left", va="top", fontsize=19, fontweight="bold", color=TEXT,
    )
    fig.text(0.035, 0.952, subtitle + (" · SON BAR AÇIK" if last_bar_open else ""),
             ha="left", va="top", fontsize=9.5, color=MUTED)
    chip_text = (
        f"Son {_fmt(current)}   {change:+.2f}%    |    "
        f"Trend {trend_text}    |    Momentum {momentum_text}    |    "
        f"RSI {_fmt(rsi_value, 1)}    RVOL {_fmt(rvol_value, 2)}x    "
        f"ATR {_fmt(atr_pct, 2)}%    ADX {_fmt(adx_value, 1)}"
    )
    fig.text(0.035, 0.929, chip_text, ha="left", va="top", fontsize=9.2, color=TEXT,
             bbox=dict(boxstyle="round,pad=0.35", facecolor="#F8FAFC", edgecolor=GRID, linewidth=0.8))
    fig.text(0.965, 0.018,
             "Gösterge teyidi ve piyasa yapısı özeti · otomatik AL/SAT değildir",
             ha="right", va="bottom", fontsize=7.5, color=MUTED)
    fig.subplots_adjust(top=0.895, bottom=0.055, left=0.04, right=0.97)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=BG, bbox_inches="tight", pad_inches=0.12)
    plt.close(fig)

    trend_role = "up" if trend_positive else "down" if trend_negative else "neutral"
    momentum_role = "up" if momentum_positive else "down" if momentum_negative else "neutral"
    snapshot = [
        ("Son", _fmt(current), "up" if change >= 0 else "down"),
        ("Değişim", f"{change:+.2f}%", "up" if change >= 0 else "down"),
        ("Trend", trend_text, trend_role),
        ("Momentum", momentum_text, momentum_role),
        ("RSI", _fmt(rsi_value, 1), "down" if rsi_value >= 70 else "up" if rsi_value <= 30 else "neutral"),
        ("RVOL", f"{rvol_value:.2f}x" if np.isfinite(rvol_value) else "—", "accent1" if rvol_value >= 1.5 else "neutral"),
        ("ATR", f"{atr_pct:.2f}%" if np.isfinite(atr_pct) else "—", "neutral"),
        ("ADX", _fmt(adx_value, 1), "accent1" if adx_value >= 25 else "neutral"),
    ]
    return snapshot


def build_technical_dashboard(
    symbol: str,
    interval: str = "1d",
    outdir: str | Path = "out",
    bars: int | None = None,
    period: str | None = None,
) -> DashboardResult:
    """Veriyi çek, tam geçmişte göstergeleri hesaplayacak pencereyi hazırla ve çiz."""
    if interval not in INTERVAL_LABELS:
        raise ValueError(f"Bilinmeyen aralık: {interval}")
    period = period or DEFAULT_PERIODS.get(interval, "2y")
    frame_full, symbol_spec = fetch_ohlcv(symbol, period=period, interval=interval)
    window = frame_full.tail(bars or default_bars(interval)).copy()
    if len(window) < 60:
        raise ValueError(f"Yetersiz veri: {len(window)} bar")
    bar_open = last_bar_is_open(frame_full.index, market=symbol_spec.market)
    generated = datetime.now().strftime("%d.%m.%Y %H:%M")
    last_ts = window.index[-1]
    subtitle = (
        f"{len(window)} bar · veri: {symbol_spec.provider} · "
        f"son bar {last_ts.strftime('%d.%m.%Y %H:%M')} · üretim {generated}"
    )
    safe_symbol = symbol_spec.display.replace("-", "_").replace("/", "_")
    path = Path(outdir) / f"{safe_symbol}_{interval}_teknik_dashboard.png"
    snapshot = render_dashboard(
        window,
        path,
        symbol=symbol_spec.display,
        interval=interval,
        subtitle=subtitle,
        last_bar_open=bar_open,
    )
    return DashboardResult(path, symbol_spec.display, interval, subtitle, snapshot)


def main() -> int:
    parser = argparse.ArgumentParser(prog="market-chart-dashboard")
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--interval", default="1d", choices=tuple(INTERVAL_LABELS))
    parser.add_argument("--outdir", default="out")
    parser.add_argument("--bars", type=int, default=None)
    parser.add_argument("--period", default=None)
    parser.add_argument("--telegram", action="store_true")
    args = parser.parse_args()

    result = build_technical_dashboard(
        args.symbol,
        args.interval,
        args.outdir,
        bars=args.bars,
        period=args.period,
    )
    print(result.path)
    if args.telegram:
        caption = tg.build_caption(
            f"{result.symbol} · {INTERVAL_LABELS.get(result.interval, result.interval)}",
            result.subtitle,
            result.snapshot,
        )
        import os

        thread_id = os.environ.get("TELEGRAM_TOPIC_ID", "").strip() or None
        tg.send_document(result.path, caption, thread_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
