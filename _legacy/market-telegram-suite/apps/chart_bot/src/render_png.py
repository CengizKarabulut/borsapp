"""PNG cizici (matplotlib), TradingView duzenine yakin.

Benimsenen dort davranis:

1. Fiyat ekseni SAGDA. Her isaretli serinin son degeri, serinin kendi renginde
   bir kutucuk olarak sag kenara yazilir.
2. Efsane yerine SATIR ICI KUNYE: panelin sol ustunde gosterge adi, parantez
   icinde ayarlari ve o anki degerleri, seri renkleriyle.
3. Mumlar elle cizilir; x ekseni tarih degil bar konumudur, etiketler sonradan
   takilir. Hafta sonu bosluklari olusmaz.
4. Metin yerlesimi olcum yapmadan hesaplanir: tek aralikli yazi tipinde
   karakter genisligi punto x 0.602'dir, ilerleme bundan turetilir. Boylece
   panel sayisi ya da cozunurluk degistiginde yerlesim kaymaz.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

from . import format as fmt
from .plotspec import ChartSpec, Panel, Trace, segment_ranges
from .theme import Theme

_DASH = {None: "solid", "dash": (0, (5, 3)), "dot": (0, (1, 2.2))}

_HEADER_IN = 0.95  # ust serit yuksekligi (inc); compact modda 0
_FOOTER_IN = 0.42
_MONO = "DejaVu Sans Mono"
#: DejaVu Sans Mono'da karakter genisligi / punto orani
_CHAR_W = 0.602


def _axes_width_pt(ax, fig_w_in: float) -> float:
    return ax.get_position().width * fig_w_in * 72.0


def _axes_height_pt(ax, fig_h_in: float) -> float:
    return ax.get_position().height * fig_h_in * 72.0


def _draw_inline(ax, entries: list[tuple[str, str]], theme: Theme, fig_w_in: float,
                 y: float = 0.985, fontsize: float = 8.0, shade: bool = False) -> None:
    """Sol uste renkli parcalardan olusan tek satir yazar.

    entries: (metin, renk rolu) ciftleri. Metinler tek aralikli yazi tipinde
    cizildigi icin ilerleme karakter sayisindan hesaplanabilir; olcum icin
    figuru cizmeye gerek kalmaz.
    """
    total_pt = _axes_width_pt(ax, fig_w_in)
    if total_pt <= 0:
        return
    step = fontsize * _CHAR_W / total_pt
    x = 0.006
    box = (dict(boxstyle="square,pad=0.12", fc=theme.c("bg"), ec="none", alpha=0.82)
           if shade else None)
    for text, role in entries:
        if x > 0.98:
            break
        ax.text(x, y, text, transform=ax.transAxes, color=theme.c(role),
                fontsize=fontsize, va="top", ha="left", family=_MONO, zorder=8,
                bbox=box)
        x += len(text) * step


def _value_tag(ax, value: float, color_hex: str, theme: Theme, text: str | None = None,
               fontsize: float = 7.5) -> None:
    """Sag eksende renkli deger kutucugu."""
    if value is None or not np.isfinite(value):
        return
    ax.annotate(
        f" {text or fmt.fiyat(value)} ",
        xy=(1.0, value), xycoords=("axes fraction", "data"),
        va="center", ha="left", fontsize=fontsize, color="#0C0C0C",
        family=_MONO,
        bbox=dict(boxstyle="square,pad=0.25", fc=color_hex, ec="none"),
        annotation_clip=False, zorder=9,
    )


def _spread_tags(tags: list[tuple[float, str, str, float]], ax, fig_h_in: float):
    """Cakisan deger etiketlerini dikeyde ayirir.

    Ilk sirada gelen (son fiyat) yerinde kalir; digerleri gerektiginde yukari
    veya asagi itilir. Etiketteki SAYI degismez, yalnizca cizim konumu kayar.
    """
    if not tags:
        return []
    low, high = ax.get_ylim()
    span = high - low
    if span <= 0:
        return tags
    # Asgari aralik, etiket kutusunun GERCEK yuksekliginden turetilir; sabit
    # bir oran kucuk izgara karolarinda yetersiz kalip etiketleri ust uste bindiriyordu.
    height_pt = max(size for _, _, _, size in tags) * 1.9
    axes_pt = _axes_height_pt(ax, fig_h_in)
    gap = span * (height_pt / axes_pt) if axes_pt > 0 else span * 0.04

    anchor = tags[0]
    others = sorted(tags[1:], key=lambda item: -item[0])
    placed: list[tuple[float, str, str, float]] = [anchor]
    used = [anchor[0]]
    for value, color_hex, text, size in others:
        y = value
        for _ in range(40):
            clash = next((u for u in used if abs(u - y) < gap), None)
            if clash is None:
                break
            y = clash + gap if y >= clash else clash - gap
        used.append(y)
        placed.append((y, color_hex, text, size))
    return placed


def _last(series: pd.Series | None) -> float:
    if series is None:
        return float("nan")
    clean = series.dropna()
    return float(clean.iloc[-1]) if len(clean) else float("nan")


def _x_ticks(index: pd.DatetimeIndex, count: int = 8) -> tuple[list[int], list[str]]:
    n = len(index)
    if n == 0:
        return [], []
    span_days = (index[-1] - index[0]).total_seconds() / 86400 if n > 1 else 1
    if 60 <= span_days <= 500:
        # TradingView gunluk gorunumunde zaman ekseni ay adlariyla okunur.
        periods = index.to_period("M")
        positions = [i for i in range(n) if i == 0 or periods[i] != periods[i - 1]]
        if len(positions) > count + 2:
            every = max(1, int(np.ceil(len(positions) / count)))
            positions = positions[::every]
        return positions, [fmt.tarih(index[p], "ay") for p in positions]

    step = max(1, n // count)
    positions = list(range(0, n, step))
    if positions[-1] < n - 1 - step * 0.55:
        positions.append(n - 1)
    mode = "dakika" if span_days <= 3 else "saat" if span_days <= 20 else (
        "gun" if span_days <= 400 else "ay")
    return positions, [fmt.tarih(index[p], mode) for p in positions]


# --------------------------------------------------------------------------
# Cizim ilkelleri
# --------------------------------------------------------------------------


def _draw_candles(ax, df: pd.DataFrame, theme: Theme, fade_last: bool = False) -> None:
    """fade_last: son bar hala olusuyorsa soluk cizilir ve boyle oldugu gorulur."""
    o = df["Open"].to_numpy(dtype="float64")
    h = df["High"].to_numpy(dtype="float64")
    low = df["Low"].to_numpy(dtype="float64")
    c = df["Close"].to_numpy(dtype="float64")
    n = len(df)
    x = np.arange(n)
    valid = ~np.isnan(o) & ~np.isnan(c)
    colors = np.where(c >= o, theme.c("up"), theme.c("down"))

    indexes = [i for i in range(n) if valid[i]]
    open_bar = indexes[-1] if (fade_last and indexes) else None

    wicks = [[(x[i], low[i]), (x[i], h[i])] for i in indexes]
    alphas = [0.42 if i == open_bar else 1.0 for i in indexes]
    ax.add_collection(LineCollection(
        wicks, colors=[colors[i] for i in indexes], alpha=None,
        linewidths=0.9, zorder=3, capstyle="butt"))

    half = 0.32
    bodies, body_colors = [], []
    for i in indexes:
        top, bottom = max(o[i], c[i]), min(o[i], c[i])
        if top == bottom:
            pad = max((h[i] - low[i]) * 0.012, abs(top) * 1e-4)
            top, bottom = top + pad, bottom - pad
        bodies.append([(x[i] - half, bottom), (x[i] - half, top),
                       (x[i] + half, top), (x[i] + half, bottom)])
        body_colors.append(colors[i])
    collection = PolyCollection(
        bodies, facecolors=body_colors, edgecolors=body_colors,
        linewidths=0.4, zorder=4)
    if open_bar is not None:
        collection.set_alpha(alphas)
    ax.add_collection(collection)


def _role_colors(colors: pd.Series, theme: Theme, fallback: str) -> list[str]:
    """Rol adlarini hex renge cevirir; bos/NaN roller yedek renge duser.

    Projeksiyon barlarinda yon serileri NaN oldugu icin bu koruma sart.
    """
    out = []
    for role in colors:
        out.append(theme.c(role) if isinstance(role, str) and role else fallback)
    return out


def _draw_trace(ax, trace: Trace, theme: Theme, n: int) -> None:
    x = np.arange(n)
    color = theme.c(trace.color)

    if trace.kind == "vprofile" and trace.y is not None and len(trace.y):
        # Hacim profili: fiyat kovalarina yatay barlar, sol kenara yaslanir
        prices = trace.y.index.to_numpy(dtype="float64")
        vols = trace.y.to_numpy(dtype="float64")
        peak = float(np.nanmax(vols)) if len(vols) else 0.0
        if peak <= 0:
            return
        height = (prices[-1] - prices[0]) / max(len(prices) - 1, 1) * 0.86
        widths = vols / peak * (n * 0.16)
        ax.barh(prices, widths, left=-0.5, height=height, color=color,
                alpha=trace.fill_alpha, linewidth=0, zorder=trace.zorder)
        return

    if trace.kind == "dots" and trace.y is not None:
        y = trace.y.to_numpy(dtype="float64")
        mask = np.isfinite(y)
        if not mask.any():
            return
        if trace.colors is not None:
            point_colors = np.array(_role_colors(trace.colors, theme, color))[mask]
        else:
            point_colors = color
        if trace.labels is not None:
            labels = trace.labels.astype(str).to_numpy()
            offset = -12 if trace.text_position == "bottom" else 12
            vertical = "top" if trace.text_position == "bottom" else "bottom"
            for position in np.flatnonzero(mask):
                label = labels[position]
                if label and label != "nan":
                    role = trace.colors.iloc[position] if trace.colors is not None else trace.color
                    label_color = theme.c(role) if isinstance(role, str) and role else color
                    ax.annotate(
                        label, (x[position], y[position]), xytext=(0, offset),
                        textcoords="offset points", ha="center", va=vertical,
                        fontsize=6.2, color="#FFFFFF", fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.32", facecolor=label_color,
                                  edgecolor="none", alpha=0.96),
                        arrowprops=dict(arrowstyle="-|>", color=label_color, lw=0.8,
                                        shrinkA=0, shrinkB=2),
                        zorder=trace.zorder + 1,
                    )
        else:
            ax.scatter(x[mask], y[mask], s=trace.width * 2.2, c=point_colors,
                       marker="o", linewidths=0, zorder=trace.zorder)
        return

    if trace.kind in {"bars", "hist"} and trace.y is not None:
        y = np.nan_to_num(trace.y.to_numpy(dtype="float64"))
        bar_colors = (_role_colors(trace.colors, theme, color)
                      if trace.colors is not None else color)
        ax.bar(x, y, width=0.7, color=bar_colors, linewidth=0, zorder=2)
        return

    if trace.kind == "band" and trace.y is not None and trace.y2 is not None:
        upper = trace.y.to_numpy(dtype="float64")
        lower = trace.y2.to_numpy(dtype="float64")
        if trace.fill_alpha:
            ax.fill_between(x, lower, upper, color=color, alpha=trace.fill_alpha,
                            linewidth=0, zorder=trace.zorder)
        style = _DASH[trace.dash]
        ax.plot(x, upper, color=color, lw=trace.width, ls=style, zorder=trace.zorder)
        ax.plot(x, lower, color=color, lw=trace.width, ls=style, zorder=trace.zorder)
        return

    if trace.kind == "cloud" and trace.y is not None and trace.y2 is not None:
        a = trace.y.to_numpy(dtype="float64")
        b = trace.y2.to_numpy(dtype="float64")
        up, down = theme.c(trace.color), theme.c(trace.color2 or trace.color)
        ax.fill_between(x, a, b, where=a >= b, color=up, alpha=trace.fill_alpha,
                        linewidth=0, zorder=trace.zorder, interpolate=True)
        ax.fill_between(x, a, b, where=a < b, color=down, alpha=trace.fill_alpha,
                        linewidth=0, zorder=trace.zorder, interpolate=True)
        ax.plot(x, a, color=up, lw=trace.width, zorder=trace.zorder, alpha=0.85)
        ax.plot(x, b, color=down, lw=trace.width, zorder=trace.zorder, alpha=0.85)
        return

    if trace.kind == "segments" and trace.y is not None and trace.colors is not None:
        y = trace.y.to_numpy(dtype="float64")
        # Yon degisiminde cizgi bilerek kopar; aksi halde flip noktalarinda
        # grafigi kesen dikey bir sicrama olusur.
        for start, end, role in segment_ranges(trace.colors):
            ax.plot(x[start:end], y[start:end], color=theme.c(role), lw=trace.width,
                    zorder=trace.zorder, solid_capstyle="round")
        return

    if trace.y is not None:
        ax.plot(x, trace.y.to_numpy(dtype="float64"), color=color, lw=trace.width,
                ls=_DASH[trace.dash], zorder=trace.zorder)


def _style_axis(ax, theme: Theme, is_last: bool) -> None:
    ax.set_facecolor(theme.c("panel"))
    ax.grid(axis="y", color=theme.c("grid"), lw=0.6,
            alpha=theme.grid_alpha, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "bottom", "left"):
        ax.spines[side].set_color(theme.c("axis"))
        ax.spines[side].set_linewidth(0.7)
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position("right")
    ax.tick_params(colors=theme.c("muted"), labelsize=7.5, length=3, width=0.6)
    ax.tick_params(labelbottom=is_last)


# --------------------------------------------------------------------------
# Kunye satirlari
# --------------------------------------------------------------------------


def _digits(price: float) -> int:
    """Fiyat buyuklugune gore ondalik basamak sayisi."""
    if abs(price) >= 1000:
        return 0
    if abs(price) >= 10:
        return 2
    return 3 if abs(price) >= 1 else 4


def _price_identity(spec: ChartSpec, theme: Theme) -> list[tuple[str, str]]:
    """Fiyat panelinin ust satiri: sembol, periyot ve OHLC."""
    df = spec.df
    closes = df["Close"].dropna()
    if not len(closes):
        return [(spec.title, "text")]
    i = closes.index[-1]
    o, h, low, c = (float(df.loc[i, k]) for k in ("Open", "High", "Low", "Close"))
    prev = float(closes.iloc[-2]) if len(closes) > 1 else c
    change = c - prev
    pct = (change / prev * 100.0) if prev else 0.0
    role = "up" if change >= 0 else "down"
    return [
        (f"{spec.title}  ", "text"),
        (f"A{fmt.fiyat(o)} ", role), (f"Y{fmt.fiyat(h)} ", role),
        (f"D{fmt.fiyat(low)} ", role), (f"K{fmt.fiyat(c)}  ", role),
        # Degisim, fiyatin kendisiyle ayni basamakta yazilir; kucuk bir fark
        # fmt.fiyat() tarafindan 4 haneye acilirsa kunye okunmaz hale gelir.
        (f"{'+' if change >= 0 else ''}{fmt.sayi(change, _digits(c))} "
         f"({'+' if pct >= 0 else ''}{fmt.sayi(pct, 2)}%)", role),
    ] + ([("   ● bar açık", "accent1")] if spec.last_bar_open else [])


def _overlay_identity(spec: ChartSpec, theme: Theme) -> list[tuple[str, str]]:
    """Fiyat uzerindeki gostergelerin adi ve son degeri."""
    entries: list[tuple[str, str]] = []
    for trace in spec.overlays:
        if not trace.legend or trace.y is None or trace.kind == "vprofile":
            continue
        value = _last(trace.y)
        role = trace.color
        if trace.colors is not None:  # yone gore renk degistiren seriler
            roles = trace.colors.dropna()
            role = str(roles.iloc[-1]) if len(roles) else trace.color
        label = trace.name if np.isnan(value) else f"{trace.name} {fmt.fiyat(value)}"
        entries.append((label + "   ", role))
    return entries


def _panel_identity(panel: Panel, theme: Theme) -> list[tuple[str, str]]:
    head = f"{panel.title}" + (f" ({panel.params})" if panel.params else "") + "  "
    entries: list[tuple[str, str]] = [(head, "muted")]
    for trace in panel.traces:
        if trace.y is None or not trace.legend:
            continue
        value = _last(trace.y)
        if np.isnan(value):
            continue
        text = fmt.kisa(value) if abs(value) >= 10000 else fmt.sayi(value, 2)
        entries.append((text + "  ", trace.color))
    return entries


# --------------------------------------------------------------------------
# Ana cizim
# --------------------------------------------------------------------------


def render_png(
    spec: ChartSpec,
    theme: Theme,
    path: str | Path,
    width_px: int = 1600,
    dpi: int = 130,
    compact: bool = False,
) -> Path:
    """compact=True: ust serit cizilmez (izgara karolarinda kullanilir)."""
    df = spec.df
    n = len(df)
    ratios = [spec.price_height] + [p.height for p in spec.panels]

    fig_w = width_px / dpi
    header_in = 0.0 if compact else _HEADER_IN
    plot_h = sum(ratios) * fig_w / 10.8
    fig_h = plot_h + header_in + _FOOTER_IN

    plt.rcParams["font.family"] = ["DejaVu Sans"]
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor=theme.c("bg"))
    gs = GridSpec(
        len(ratios), 1, height_ratios=ratios, hspace=0.07,
        top=1 - (header_in / fig_h) - (0.012 if compact else 0.0),
        bottom=_FOOTER_IN / fig_h, left=0.012, right=0.918,
    )

    if not compact:
        _draw_top_band(fig, spec, theme, fig_h)

    filled = df["Close"].notna().to_numpy().nonzero()[0]
    last_real = int(filled[-1]) if len(filled) else n - 1

    axes = []
    price_ax = fig.add_subplot(gs[0])
    axes.append(price_ax)
    if last_real < n - 1:
        price_ax.axvspan(last_real + 0.5, n - 0.5, color=theme.c("grid"),
                         alpha=0.20, zorder=0)
    _draw_candles(price_ax, df, theme, fade_last=spec.last_bar_open)
    for trace in spec.overlays:
        _draw_trace(price_ax, trace, theme, n)
    _style_axis(price_ax, theme, is_last=not spec.panels)
    if spec.log_price:
        # Genis aralikli serilerde (orn. 100 -> 700) lineer eksen ilk aylari
        # ezer. Log olcekte esit yuzde hareketleri esit mesafe kaplar.
        price_ax.set_yscale("log")
        price_ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1, 2, 3, 5, 7)))
        price_ax.yaxis.set_minor_formatter(NullFormatter())
    # Log eksende basamak sayisi degerden degere degisirse etiketler okunmaz
    # hale gelir ("5,000" bes, "500,00" bes yuz). eksen() sondaki sifirlari atar.
    price_ax.yaxis.set_major_formatter(FuncFormatter(
        lambda v, _: fmt.eksen(v) if spec.log_price else fmt.fiyat(v)))

    # Satir araligi eksen yuksekligine gore hesaplanir; sabit oran kullanilirsa
    # kucuk karolarda satirlar ust uste biner.
    price_h_pt = _axes_height_pt(price_ax, fig_h)
    def row(i: int, size: float) -> float:
        return 0.985 - sum(s * 2.05 for s in [8.5, 7.5, 7.0][:i]) / max(price_h_pt, 1)

    _draw_inline(price_ax, _price_identity(spec, theme), theme, fig_w,
                 y=row(0, 8.5), fontsize=8.5, shade=True)
    overlays = _overlay_identity(spec, theme)
    if overlays:
        _draw_inline(price_ax, overlays, theme, fig_w, y=row(1, 7.5),
                     fontsize=7.5, shade=True)
    if spec.note:
        _draw_inline(price_ax, [(spec.note, "muted")], theme, fig_w,
                     y=row(2 if overlays else 1, 7.0), fontsize=7.0, shade=True)

    # Sag eksen etiketleri. Son fiyat oncelikli; gostergeler onunla ya da
    # birbiriyle cakisirsa dikeyde itilir, aksi halde ust uste binip okunmaz olur.
    tags: list[tuple[float, str, str, float]] = []
    closes = df["Close"].dropna()
    if len(closes):
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else last
        role = "up" if last >= prev else "down"
        price_ax.axhline(last, color=theme.c(role), lw=0.7, ls=(0, (4, 3)),
                         alpha=0.6, zorder=5)
        tags.append((last, theme.c(role), fmt.fiyat(last), 8.5))

    for trace in spec.overlays:
        if not trace.tag or trace.y is None:
            continue
        value = _last(trace.y)
        if not np.isfinite(value):
            continue
        role = trace.color
        if trace.colors is not None:
            roles = trace.colors.dropna()
            role = str(roles.iloc[-1]) if len(roles) else trace.color
        tags.append((value, theme.c(role), fmt.fiyat(value), 7.5))

    for value, color_hex, text, size in _spread_tags(tags, price_ax, fig_h):
        _value_tag(price_ax, value, color_hex, theme, text=text, fontsize=size)

    for i, panel in enumerate(spec.panels):
        ax = fig.add_subplot(gs[i + 1], sharex=price_ax)
        axes.append(ax)
        if last_real < n - 1:
            ax.axvspan(last_real + 0.5, n - 0.5, color=theme.c("grid"),
                       alpha=0.20, zorder=0)
        for hline in panel.hlines:
            ax.axhline(hline.value, color=theme.c(hline.color), lw=hline.width,
                       ls=_DASH[hline.dash], alpha=0.55, zorder=1)
        if panel.zero_line:
            ax.axhline(0, color=theme.c("axis"), lw=0.9, zorder=1)
        for trace in panel.traces:
            _draw_trace(ax, trace, theme, n)
        if panel.yrange:
            ax.set_ylim(*panel.yrange)
        ax.yaxis.set_major_formatter(FuncFormatter(
            lambda v, _: fmt.kisa(v) if abs(v) >= 10000 else fmt.sayi(v, 2)))
        _style_axis(ax, theme, is_last=(i == len(spec.panels) - 1))
        # Kunye cizimlerin ustune binmesin diye HER panele tepeden pay birakilir.
        # Sabit araliklilar (0-100 gibi) da dahil; aksi halde baslik cizgiye deger.
        low, high = ax.get_ylim()
        ax.set_ylim(low, high + (high - low) * 0.20)
        _draw_inline(ax, _panel_identity(panel, theme), theme, fig_w,
                     y=0.97, fontsize=7.5, shade=True)
        primary = next((t for t in panel.traces if t.y is not None and t.legend), None)
        if primary is not None:
            value = _last(primary.y)
            text = fmt.kisa(value) if abs(value) >= 10000 else fmt.sayi(value, 2)
            _value_tag(ax, value, theme.c(primary.color), theme, text=text)

    ticks, labels = _x_ticks(df.index)
    axes[-1].set_xticks(ticks)
    axes[-1].set_xticklabels(labels, fontsize=7.5)
    price_ax.set_xlim(-1, n)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=theme.c("bg"), dpi=dpi)
    plt.close(fig)
    return path


def _draw_top_band(fig, spec: ChartSpec, theme: Theme, fig_h: float) -> None:
    """Ust serit: solda sembol, sagda durum rozetleri."""
    band = fig.add_axes([0.0, 1 - _HEADER_IN / fig_h, 1.0, _HEADER_IN / fig_h])
    band.set_axis_off()
    band.set_xlim(0, 1)
    band.set_ylim(0, 1)
    band.patch.set_alpha(0.0)

    long_title = len(spec.title) > 46
    title_size = 12.5 if long_title else 16
    band.text(0.012, 0.68, spec.title, color=theme.c("text"), fontsize=title_size,
              fontweight="bold", va="center", ha="left")
    band.text(0.012, 0.26, spec.subtitle, color=theme.c("muted"), fontsize=8.5,
              va="center", ha="left")

    chips = spec.snapshot
    if not chips:
        return
    right_edge = 0.918
    block_start = max(0.50 if long_title else 0.42, right_edge - 0.068 * len(chips))
    slot = (right_edge - block_start) / len(chips)
    for i, (label, value, role) in enumerate(chips):
        cx = block_start + slot * (i + 0.5)
        band.text(cx, 0.66, value, color=theme.c(role), fontsize=10,
                  fontweight="bold", va="center", ha="center", family=_MONO)
        band.text(cx, 0.28, label.upper(), color=theme.c("muted"), fontsize=6.5,
                  va="center", ha="center")
