"""Etkilesimli HTML cizici (plotly).

PNG ile ayni ChartSpec'i okur. Fark yalnizca arka uctadir: burada zoom,
hover ve seri acip kapatma var. x ekseni yine kategorik (bar konumu), boylece
hafta sonu bosluklari olusmaz ve iki cikti ayni gorunur.
"""

from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .plotspec import ChartSpec, Trace, segment_ranges
from .theme import Theme

_DASH = {None: "solid", "dash": "dash", "dot": "dot"}


def _rgba(hex_color: str, alpha: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _x_labels(index: pd.DatetimeIndex) -> list[str]:
    span_days = (index[-1] - index[0]).total_seconds() / 86400 if len(index) > 1 else 1
    fmt = "%Y-%m-%d %H:%M" if span_days <= 30 else "%Y-%m-%d"
    return [ts.strftime(fmt) for ts in index]


def _add_trace(fig, trace: Trace, theme: Theme, x: list[str], row: int) -> None:
    color = theme.c(trace.color)
    dash = _DASH[trace.dash]

    def line(y, name, col, width, legend=True, fill=None, fillcolor=None, dash_=dash):
        fig.add_trace(
            go.Scatter(
                x=x,
                y=y,
                name=name,
                mode="lines",
                line=dict(color=col, width=width, dash=dash_, shape="linear"),
                fill=fill,
                fillcolor=fillcolor,
                showlegend=legend,
                legendgroup=trace.name,
                hovertemplate="%{fullData.name}: %{y:.4g}<extra></extra>",
                connectgaps=False,
            ),
            row=row,
            col=1,
        )

    if trace.kind == "vprofile" and trace.y is not None and len(trace.y):
        prices = trace.y.index.to_numpy(dtype="float64")
        vols = trace.y.to_numpy(dtype="float64")
        peak = float(vols.max()) if len(vols) else 0.0
        if peak <= 0:
            return
        # Yatay hacim profili: kategorik x ekseninde bar cizilemedigi icin
        # ilk N kategoriye yayilan yatay bir bar grubu kullanilir.
        fig.add_trace(
            go.Bar(
                x=[v / peak * (len(x) * 0.16) for v in vols],
                y=prices, orientation="h", name=trace.name,
                marker=dict(color=_rgba(color, trace.fill_alpha), line=dict(width=0)),
                showlegend=False, hoverinfo="skip", xaxis="x2", yaxis="y",
            )
        )
        return

    if trace.kind == "dots" and trace.y is not None:
        point_colors = [
            theme.c(r) if isinstance(r, str) and r else color for r in trace.colors
        ] if trace.colors is not None else color
        fig.add_trace(
            go.Scatter(
                x=x, y=trace.y.to_numpy(dtype="float64"), name=trace.name,
                mode="markers+text" if trace.labels is not None else "markers",
                text=trace.labels.astype(str).tolist() if trace.labels is not None else None,
                textposition="bottom center" if trace.text_position == "bottom" else "top center",
                textfont=dict(color=color, size=9),
                marker=dict(color=point_colors, size=5),
                showlegend=trace.legend,
                hovertemplate="%{fullData.name}: %{text}<br>%{y:.4g}<extra></extra>",
            ),
            row=row, col=1,
        )
        return

    if trace.kind in {"bars", "hist"} and trace.y is not None:
        colors = (
            [theme.c(r) if isinstance(r, str) and r else color for r in trace.colors]
            if trace.colors is not None
            else color
        )
        fig.add_trace(
            go.Bar(
                x=x,
                y=trace.y.to_numpy(dtype="float64"),
                name=trace.name,
                marker=dict(color=colors, line=dict(width=0)),
                showlegend=trace.legend,
                hovertemplate="%{fullData.name}: %{y:.4g}<extra></extra>",
            ),
            row=row,
            col=1,
        )
        return

    if trace.kind == "band" and trace.y is not None and trace.y2 is not None:
        line(trace.y2.to_numpy(dtype="float64"), f"{trace.name} alt", color, trace.width, legend=False)
        line(
            trace.y.to_numpy(dtype="float64"),
            trace.name,
            color,
            trace.width,
            legend=trace.legend,
            fill="tonexty" if trace.fill_alpha else None,
            fillcolor=_rgba(color, trace.fill_alpha) if trace.fill_alpha else None,
        )
        return

    if trace.kind == "cloud" and trace.y is not None and trace.y2 is not None:
        a = trace.y.to_numpy(dtype="float64")
        b = trace.y2.to_numpy(dtype="float64")
        up = theme.c(trace.color)
        down = theme.c(trace.color2 or trace.color)
        # Iki renkli bulut: taban cizgisine gore iki ayri dolgu
        line(b, "Senkou B", down, trace.width, legend=False)
        line(np.fmax(a, b), "Kumo yukari", up, 0.01, legend=False,
             fill="tonexty", fillcolor=_rgba(up, trace.fill_alpha))
        line(b, "Senkou B ", down, 0.01, legend=False)
        line(np.fmin(a, b), "Kumo asagi", down, 0.01, legend=False,
             fill="tonexty", fillcolor=_rgba(down, trace.fill_alpha))
        line(a, trace.name, up, trace.width, legend=trace.legend)
        return

    if trace.kind == "segments" and trace.y is not None and trace.colors is not None:
        y = trace.y.to_numpy(dtype="float64")
        shown = False
        for start, end, role in segment_ranges(trace.colors):
            stop = min(end + 1, len(x))
            seg = np.full(len(x), np.nan)
            seg[start:stop] = y[start:stop]
            line(seg, trace.name, theme.c(role), trace.width, legend=trace.legend and not shown)
            shown = True
        return

    if trace.y is not None:
        line(trace.y.to_numpy(dtype="float64"), trace.name, color, trace.width, legend=trace.legend)


def build_figure(spec: ChartSpec, theme: Theme) -> go.Figure:
    df = spec.df
    x = _x_labels(df.index)
    ratios = [spec.price_height] + [p.height for p in spec.panels]
    total = sum(ratios)

    fig = make_subplots(
        rows=len(ratios),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.022,
        row_heights=[r / total for r in ratios],
    )

    fig.add_trace(
        go.Candlestick(
            x=x,
            open=df["Open"],
            high=df["High"],
            low=df["Low"],
            close=df["Close"],
            name="Fiyat",
            increasing=dict(line=dict(color=theme.c("up"), width=1), fillcolor=theme.c("up")),
            decreasing=dict(line=dict(color=theme.c("down"), width=1), fillcolor=theme.c("down")),
            showlegend=False,
        ),
        row=1,
        col=1,
    )
    for trace in spec.overlays:
        _add_trace(fig, trace, theme, x, row=1)

    for i, panel in enumerate(spec.panels, start=2):
        for trace in panel.traces:
            _add_trace(fig, trace, theme, x, row=i)
        for hline in panel.hlines:
            fig.add_hline(
                y=hline.value,
                line=dict(color=theme.c(hline.color), width=hline.width, dash=_DASH[hline.dash]),
                opacity=0.6,
                row=i,
                col=1,
            )
        if panel.zero_line:
            fig.add_hline(y=0, line=dict(color=theme.c("axis"), width=1), row=i, col=1)
        if panel.yrange:
            fig.update_yaxes(range=list(panel.yrange), row=i, col=1)

    if spec.log_price:
        fig.update_yaxes(type="log", row=1, col=1)

    last = float(df["Close"].dropna().iloc[-1])
    fig.add_hline(
        y=last,
        line=dict(color=theme.c("muted"), width=1, dash="dot"),
        annotation_text=f"{last:,.2f}".replace(",", " "),
        annotation_position="right",
        annotation_font=dict(color=theme.c("text"), size=11),
        row=1,
        col=1,
    )

    # Panel kunyeleri: PNG'deki satir ici basliklarin karsiligi. Plotly'nin
    # subplot_titles'i ortalar ve panelin ustune iter; burada sol uste sabitlenir.
    for i, panel in enumerate(spec.panels, start=2):
        values = []
        for tr in panel.traces:
            if tr.y is None or not tr.legend:
                continue
            clean = tr.y.dropna()
            if len(clean):
                values.append(f'<span style="color:{theme.c(tr.color)}">'
                              f"{float(clean.iloc[-1]):.4g}</span>")
        head = panel.title + (f" ({panel.params})" if panel.params else "")
        fig.add_annotation(
            text=" ".join([f'<span style="color:{theme.c("muted")}">{head}</span>'] + values),
            xref=f"x{i} domain" if i > 1 else "x domain", yref=f"y{i} domain",
            x=0.004, y=1.0, xanchor="left", yanchor="top", showarrow=False,
            font=dict(family=theme.font_mono, size=10.5), align="left",
        )

    fig.update_layout(
        template="plotly_dark" if theme.name in {"ink", "tv"} else "plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=theme.c("panel"),
        font=dict(family=theme.font_body, color=theme.c("text"), size=12),
        margin=dict(l=14, r=78, t=30, b=34),
        height=max(560, int(total * 155)),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=theme.c("bg"),
            bordercolor=theme.c("axis"),
            font=dict(family=theme.font_mono, size=11, color=theme.c("text")),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.005, xanchor="left", x=0,
            font=dict(size=11, color=theme.c("muted")), bgcolor="rgba(0,0,0,0)",
        ),
        barmode="overlay",
        dragmode="pan",
        # Hacim profili kendi gorunmez x ekseninde durur; fiyat eksenini paylasir
        xaxis2=dict(overlaying="x", side="top", showgrid=False, showticklabels=False,
                    range=[0, len(x)], fixedrange=True),
    )
    fig.update_xaxes(
        type="category",
        showgrid=True,
        gridcolor=theme.c("grid"),
        gridwidth=1,
        linecolor=theme.c("axis"),
        tickfont=dict(color=theme.c("muted"), size=10),
        nticks=10,
        rangeslider=dict(visible=False),
        spikemode="across",
        spikecolor=theme.c("axis"),
        spikethickness=1,
        spikedash="dot",
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=theme.c("grid"),
        gridwidth=1,
        linecolor=theme.c("axis"),
        tickfont=dict(color=theme.c("muted"), size=10),
        zeroline=False,
        side="right",  # TradingView'daki gibi fiyat olcegi sagda
        showspikes=True,
        spikemode="across",
        spikecolor=theme.c("axis"),
        spikethickness=1,
        spikedash="dot",
    )
    return fig


_PAGE = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · Grafik</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: {bg}; --panel: {panel}; --grid: {grid}; --axis: {axis};
    --text: {text}; --muted: {muted}; --up: {up}; --down: {down}; --accent: {accent};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: 'IBM Plex Sans', system-ui, sans-serif;
    -webkit-font-smoothing: antialiased;
  }}
  .wrap {{ max-width: 1440px; margin: 0 auto; padding: 28px 20px 48px; }}
  header {{
    display: flex; flex-wrap: wrap; align-items: flex-end; gap: 12px 28px;
    border-bottom: 1px solid var(--axis); padding-bottom: 16px;
  }}
  .ident {{ display: flex; flex-direction: column; gap: 4px; margin-right: auto; }}
  .ticker {{
    font-family: 'IBM Plex Mono', monospace; font-weight: 600;
    font-size: clamp(26px, 4vw, 38px); letter-spacing: -0.02em; line-height: 1;
  }}
  .meta {{ color: var(--muted); font-size: 13px; }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 8px 10px; }}
  .chip {{
    background: var(--panel); border: 1px solid var(--axis); border-radius: 3px;
    padding: 6px 10px; min-width: 78px;
  }}
  .chip .k {{ display: block; font-size: 10px; text-transform: uppercase;
              letter-spacing: 0.08em; color: var(--muted); margin-bottom: 3px; }}
  .chip .v {{ font-family: 'IBM Plex Mono', monospace; font-size: 15px; font-weight: 500; }}

  nav {{ display: flex; flex-wrap: wrap; gap: 2px; margin-top: 20px;
         border-bottom: 1px solid var(--axis); }}
  nav button {{
    appearance: none; background: none; border: 0; border-bottom: 2px solid transparent;
    color: var(--muted); font-family: inherit; font-size: 13px; font-weight: 500;
    padding: 9px 14px; cursor: pointer; transition: color .12s, border-color .12s;
  }}
  nav button:hover {{ color: var(--text); }}
  nav button[aria-selected="true"] {{ color: var(--text); border-bottom-color: var(--accent); }}
  nav button:focus-visible {{ outline: 2px solid var(--accent); outline-offset: -2px; }}

  .frame {{ display: none; padding-top: 6px; }}
  .frame[data-active="true"] {{ display: block; }}
  .frame-note {{ color: var(--muted); font-size: 12.5px; margin: 12px 2px 0; }}

  footer {{
    margin-top: 24px; padding-top: 14px; border-top: 1px solid var(--axis);
    color: var(--muted); font-size: 12px; line-height: 1.7;
  }}
  footer code {{ font-family: 'IBM Plex Mono', monospace; color: var(--text); }}
  @media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="ident">
      <div class="ticker">{ticker}</div>
      <div class="meta">{subtitle}</div>
    </div>
    <div class="chips">{chips}</div>
  </header>
  <nav role="tablist">{tabs}</nav>
  {frames}
  <footer>
    Veri kaynağı: <code>{source}</code> · Üretim: {generated}
    <div>Bu sayfa teknik gösterge görselleştirmesidir; yatırım tavsiyesi değildir.</div>
  </footer>
</div>
<script>
  (function () {{
    var tabs = Array.prototype.slice.call(document.querySelectorAll('nav button'));
    var frames = Array.prototype.slice.call(document.querySelectorAll('.frame'));
    function show(key) {{
      tabs.forEach(function (t) {{ t.setAttribute('aria-selected', String(t.dataset.key === key)); }});
      frames.forEach(function (f) {{
        var on = f.dataset.key === key;
        f.dataset.active = String(on);
        if (on && window.Plotly) {{
          // Gizliyken cizilen grafik yanlis genislikte kalir; gorununce olcusu tazelenir.
          f.querySelectorAll('.plotly-graph-div').forEach(function (d) {{ Plotly.Plots.resize(d); }});
        }}
      }});
      history.replaceState(null, '', '#' + key);
    }}
    tabs.forEach(function (t) {{ t.addEventListener('click', function () {{ show(t.dataset.key); }}); }});
    var initial = (location.hash || '').replace('#', '');
    show(tabs.some(function (t) {{ return t.dataset.key === initial; }}) ? initial : tabs[0].dataset.key);
  }})();
</script>
</body>
</html>
"""


def _chips_html(spec: ChartSpec, theme: Theme) -> str:
    return "".join(
        f'<div class="chip"><span class="k">{html.escape(label)}</span>'
        f'<span class="v" style="color:{theme.c(role)}">{html.escape(value)}</span></div>'
        for label, value, role in spec.snapshot
    )


def render_html(
    frames: list[tuple[str, str, str, ChartSpec]],
    theme: Theme,
    path: str | Path,
    ticker: str,
    subtitle: str,
    source: str,
    generated: str,
    embed_js: bool = False,
) -> Path:
    """Sekmeli tek sayfa uretir.

    frames: (anahtar, sekme basligi, aciklama, ChartSpec) listesi. Her kare
    kendi grafigini tasir; plotly.js yalnizca bir kez yuklenir.
    """
    if not frames:
        raise ValueError("En az bir kare gerekli")

    config = {
        "scrollZoom": True,
        "displaylogo": False,
        "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d"],
        "toImageButtonOptions": {"format": "png", "scale": 2, "filename": ticker},
    }

    tabs_html, frames_html = [], []
    for i, (key, title, note, spec) in enumerate(frames):
        fig = build_figure(spec, theme)
        chart = fig.to_html(
            full_html=False,
            include_plotlyjs=(True if embed_js else "cdn") if i == 0 else False,
            config=config,
        )
        tabs_html.append(
            f'<button role="tab" data-key="{html.escape(key)}" '
            f'aria-selected="{str(i == 0).lower()}">{html.escape(title)}</button>'
        )
        frames_html.append(
            f'<section class="frame" data-key="{html.escape(key)}" '
            f'data-active="{str(i == 0).lower()}">{chart}'
            f'<p class="frame-note">{html.escape(note)}</p></section>'
        )

    page = _PAGE.format(
        title=html.escape(ticker),
        ticker=html.escape(ticker),
        subtitle=html.escape(subtitle),
        chips=_chips_html(frames[0][3], theme),
        tabs="".join(tabs_html),
        frames="".join(frames_html),
        source=html.escape(source),
        generated=html.escape(generated),
        bg=theme.c("bg"),
        panel=theme.c("panel"),
        grid=theme.c("grid"),
        axis=theme.c("axis"),
        text=theme.c("text"),
        muted=theme.c("muted"),
        up=theme.c("up"),
        down=theme.c("down"),
        accent=theme.c("accent1"),
    )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
