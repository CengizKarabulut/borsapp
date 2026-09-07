"""Cizim tarifi (backend'den bagimsiz).

indicators.py'nin urettigi Series sozlugu burada "ne cizilecek" tarifine
donusur: fiyat uzerine binen katmanlar (overlay) ve alttaki ayri paneller.
matplotlib ve plotly arka uclari bu tarifi okuyup kendi dilinde cizer. Yeni
bir gosterge eklemek icin tek yapilacak sey buraya bir builder yazmaktir.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Trace:
    """Tek bir cizgi/bant/bar serisi."""

    name: str
    kind: str = "line"  # line | band | cloud | bars | hist | segments
    y: pd.Series | None = None
    y2: pd.Series | None = None  # band/cloud/segments icin ikinci sinir
    color: str = "accent1"  # tema rol adi
    color2: str | None = None  # cloud/bars icin ikinci renk
    width: float = 1.4
    dash: str | None = None  # None | dash | dot
    fill_alpha: float = 0.0
    colors: pd.Series | None = None  # bar/segment basina rol adi
    labels: pd.Series | None = None  # nokta yaninda kisa formasyon etiketi
    text_position: str = "top"
    legend: bool = True
    zorder: int = 2
    tag: bool = False  # sag eksende renkli deger etiketi cizilsin mi


@dataclass
class HLine:
    value: float
    color: str = "muted"
    dash: str | None = "dot"
    label: str | None = None
    width: float = 0.9


@dataclass
class Panel:
    """Fiyatin altindaki bagimsiz cizim alani."""

    key: str
    title: str
    traces: list[Trace]
    height: float = 1.0  # fiyat paneline gore oransal yukseklik
    hlines: list[HLine] = field(default_factory=list)
    yrange: tuple[float, float] | None = None
    zero_line: bool = False
    params: str = ""  # baslikta parantez icinde gosterilecek ayarlar


@dataclass
class ChartSpec:
    df: pd.DataFrame
    overlays: list[Trace]
    panels: list[Panel]
    title: str
    subtitle: str
    snapshot: list[tuple[str, str, str]]  # (etiket, deger, renk rolu)
    note: str = ""  # gorunum aciklamasi (baslikta ucuncu satir)
    last_bar_open: bool = False  # son bar hala olusuyorsa soluk cizilir
    log_price: bool = False  # fiyat ekseni logaritmik mi
    price_height: float = 3.4


# --------------------------------------------------------------------------
# Gosterge -> Trace/Panel donusturuculeri
# --------------------------------------------------------------------------

#: Ortalamalar amber -> camgobegi -> mor sirasiyla; VWAP ve Ichimoku
#: cizgileri baska belirtec kullanir, boylece hicbir ikisi ayni renk olmaz.
_MA_COLORS = ("accent1", "accent3", "accent2", "accent4")


def _recent_candle_series(series: pd.Series, bars: int = 2) -> pd.Series:
    """Formasyon rozetlerini yalnizca son tamamlanma bolgesinde tutar."""
    out = series.copy()
    if len(out) > bars:
        if pd.api.types.is_object_dtype(out.dtype):
            out.iloc[:-bars] = ""
        else:
            out.iloc[:-bars] = np.nan
    return out


def _candlestick_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(
            name="Bullish mum", kind="dots",
            y=_recent_candle_series(s["CANDLE_BULL_Y"]), color="up",
            labels=_recent_candle_series(s["CANDLE_BULL_LABEL"]),
            text_position="bottom", width=10, legend=False, zorder=7,
        ),
        Trace(
            name="Bearish mum", kind="dots",
            y=_recent_candle_series(s["CANDLE_BEAR_Y"]), color="down",
            labels=_recent_candle_series(s["CANDLE_BEAR_LABEL"]),
            text_position="top", width=10, legend=False, zorder=7,
        ),
        Trace(
            name="Nötr mum", kind="dots",
            y=_recent_candle_series(s["CANDLE_NEUTRAL_Y"]), color="muted",
            labels=_recent_candle_series(s["CANDLE_NEUTRAL_LABEL"]),
            text_position="bottom", width=8, legend=False, zorder=6,
        ),
    ]


def _ma_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    keys = [k for k in s if k.startswith(("EMA", "SMA"))]
    # Uzun periyot daha kalin cizilsin
    keys.sort(key=lambda k: int("".join(ch for ch in k if ch.isdigit()) or 0))
    out = []
    for i, key in enumerate(keys):
        length = int("".join(ch for ch in key if ch.isdigit()) or 0)
        out.append(
            Trace(
                name=key,
                y=s[key],
                color=_MA_COLORS[i % len(_MA_COLORS)],
                width=1.1 + min(length, 200) / 250.0,
                zorder=3,
                tag=True,
            )
        )
    return out


def _bb_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(
            name="Bollinger 20/2",
            kind="band",
            y=s["BB_upper"],
            y2=s["BB_lower"],
            color="neutral",
            width=0.9,
            dash="dash",
            fill_alpha=0.07,
            zorder=1,
        ),
        Trace(name="BB orta", y=s["BB_mid"], color="neutral", width=0.8, dash="dot", legend=False),
    ]


def _supertrend_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    roles = s["ST_dir"].map({1.0: "up", -1.0: "down"})
    return [
        Trace(
            name="Supertrend",
            kind="segments",
            y=s["ST_line"],
            colors=roles,
            width=1.9,
            zorder=4,
            tag=True,
        )
    ]


def _ichimoku_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(
            name="Kumo",
            kind="cloud",
            y=s["ICH_span_a"],
            y2=s["ICH_span_b"],
            color="up_soft",
            color2="down_soft",
            fill_alpha=0.20,
            width=0.7,
            zorder=0,
        ),
        Trace(name="Tenkan 9", y=s["ICH_tenkan"], color="#2962FF", width=1.0),
        Trace(name="Kijun 26", y=s["ICH_kijun"], color="#B71C1C", width=1.2, tag=True),
        Trace(name="Chikou 26", y=s["ICH_chikou"], color="#43A047",
              width=0.9, legend=False),
    ]


def _vwap_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    traces: list[Trace] = []
    for multiplier, role, alpha in ((3, "accent3", 0.03), (2, "up", 0.05), (1, "accent1", 0.07)):
        traces.append(
            Trace(
                name=f"VWAP ±{multiplier}σ",
                kind="band",
                y=s[f"VWAP_upper_{multiplier}"],
                y2=s[f"VWAP_lower_{multiplier}"],
                color=role,
                width=0.7,
                dash="dot",
                fill_alpha=alpha,
                legend=multiplier == 1,
                zorder=1,
            )
        )
    traces.append(Trace(name="Auto AVWAP", y=s["VWAP"], color="vwap", width=1.5, zorder=3, tag=True))
    return traces

def clip_outliers(series: pd.Series, quantile: float = 0.95,
                  headroom: float = 1.25) -> tuple[float, int]:
    """Panel tavani ve tavani asan bar sayisini hesaplar.

    Tek bir devasa hacim bari, panelin geri kalanini duz cizgiye cevirir.
    Tavani 95. yuzdelige gore belirleyip asan barlari isaretlemek, hem gunluk
    hacmi okunur kilar hem de aykiri degeri gizlemez.
    """
    clean = series.dropna()
    clean = clean[clean > 0]
    if len(clean) < 10:
        return float("nan"), 0
    cap = float(clean.quantile(quantile)) * headroom
    if not np.isfinite(cap) or cap <= 0:
        return float("nan"), 0
    exceeding = int((clean > cap).sum())
    # Tavan zaten en yuksek bara yakinsa kirpmaya gerek yok
    if exceeding == 0 or cap >= float(clean.max()) * 0.92:
        return float("nan"), 0
    return cap, exceeding


def _volume_panel(df: pd.DataFrame, s: dict[str, pd.Series]) -> Panel:
    vol = s["VOL"]
    cap, exceeding = clip_outliers(vol)
    roles = np.where(df["Close"] >= df["Open"], "up", "down")
    if np.isfinite(cap):
        # Tavani asan barlar farkli renkte: kirpildiklari gizlenmesin
        roles = np.where(vol.to_numpy() > cap, "accent2", roles)
    params = "ort. 20" + (f" · {exceeding} bar kırpıldı" if exceeding else "")
    return Panel(
        key="volume",
        title="Hacim",
        params=params,
        height=0.75,
        traces=[
            Trace(
                name="Hacim",
                kind="bars",
                y=vol,
                colors=pd.Series(roles, index=df.index),
                legend=False,
            ),
            Trace(name="Hacim ort. 20", y=s["VOL_ma"], color="accent1", width=1.2),
        ],
        yrange=(0, cap) if np.isfinite(cap) else None,
    )


def _divergence_traces(s: dict[str, pd.Series], prefix: str) -> list[Trace]:
    """Teyitli normal uyumsuzlukları osilatör panelinde gösterir."""
    bull = s.get(f"{prefix}_div_bull")
    bear = s.get(f"{prefix}_div_bear")
    if bull is None or bear is None:
        return []
    return [
        Trace(name="Bull uyumsuzluk", y=bull, color="up", width=2.0, legend=False, zorder=5),
        Trace(name="Bear uyumsuzluk", y=bear, color="down", width=2.0, legend=False, zorder=5),
        Trace(name="Bull", kind="dots", y=s.get(f"{prefix}_div_bull_points"), color="up", width=3.0, legend=False, zorder=6),
        Trace(name="Bear", kind="dots", y=s.get(f"{prefix}_div_bear_points"), color="down", width=3.0, legend=False, zorder=6),
    ]


def _rsi_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="rsi",
        title="RSI",
        params="14",
        height=0.8,
        traces=[
            Trace(name="RSI", y=s["RSI"], color="accent2", width=1.5),
            Trace(name="RSI MA 14", y=s["RSI_ma"], color="#FDD835", width=1.0),
            *_divergence_traces(s, "RSI"),
        ],
        hlines=[
            HLine(70, "down", "dash", "70"),
            HLine(50, "muted", "dot", "50"),
            HLine(30, "up", "dash", "30"),
        ],
        yrange=(0, 100),
    )


def _macd_panel(s: dict[str, pd.Series]) -> Panel:
    hist = s["MACD_hist"]
    rising = hist.diff() >= 0
    roles = pd.Series(
        np.where(hist >= 0, np.where(rising, "up", "up_soft"), np.where(rising, "down_soft", "down")),
        index=hist.index,
    )
    return Panel(
        key="macd",
        title="MACD",
        params="12, 26, 9",
        height=0.85,
        traces=[
            Trace(name="Histogram", kind="hist", y=hist, colors=roles, legend=False),
            Trace(name="MACD", y=s["MACD"], color="accent3", width=1.4),
            Trace(name="Sinyal", y=s["MACD_signal"], color="accent1", width=1.2),
            *_divergence_traces(s, "MACD"),
        ],
        zero_line=True,
    )


def _smi_panel(s: dict[str, pd.Series]) -> Panel:
    upper = pd.Series(40.0, index=s["SMI"].index)
    lower = pd.Series(-40.0, index=s["SMI"].index)
    return Panel(
        key="smi", title="SMI", params="10, 3, 3", height=0.75,
        traces=[
            Trace(name="Nötr bölge", kind="band", y=upper, y2=lower,
                  color="accent3", width=0, fill_alpha=0.08, legend=False, zorder=0),
            Trace(name="SMI", y=s["SMI"], color="accent3", width=1.5),
            Trace(name="SMI EMA", y=s["SMI_signal"], color="accent1", width=1.2),
            *_divergence_traces(s, "SMI"),
        ],
        hlines=[HLine(40, "down", "dash", "40"), HLine(-40, "up", "dash", "-40")],
        zero_line=True,
        yrange=(-120, 120),
    )


def _stochrsi_panel(s: dict[str, pd.Series]) -> Panel:
    upper = pd.Series(80.0, index=s["SRSI_k"].index)
    lower = pd.Series(20.0, index=s["SRSI_k"].index)
    return Panel(
        key="stochrsi",
        title="Stoch RSI",
        params="14, 14, 3, 3",
        height=0.7,
        traces=[
            Trace(name="20–80 bölgesi", kind="band", y=upper, y2=lower,
                  color="accent3", width=0, fill_alpha=0.08, legend=False, zorder=0),
            Trace(name="%K", y=s["SRSI_k"], color="accent3", width=1.4),
            Trace(name="%D", y=s["SRSI_d"], color="accent1", width=1.1),
        ],
        hlines=[HLine(80, "down", "dash", "80"), HLine(20, "up", "dash", "20")],
        yrange=(0, 100),
    )


def _adx_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="adx",
        title="ADX / DMI",
        params="14",
        height=0.75,
        traces=[
            Trace(name="+DI", y=s["DI_plus"], color="accent3", width=1.1),
            Trace(name="-DI", y=s["DI_minus"], color="accent1", width=1.1),
            Trace(name="ADX", y=s["ADX"], color="accent4", width=1.6),
        ],
        hlines=[HLine(25, "muted", "dash", "25")],
    )


def _bbstate_panel(s: dict[str, pd.Series]) -> Panel:
    """%B: fiyatin bantlar icindeki konumu. 1 = ust bant, 0 = alt bant."""
    return Panel(
        key="bbstate",
        title="Bollinger %B",
        params="20, 2",
        height=0.7,
        traces=[Trace(name="%B", y=s["BB_percent_b"], color="accent3", width=1.4)],
        hlines=[
            HLine(1.0, "down", "dash", "1"),
            HLine(0.5, "muted", "dot", "0.5"),
            HLine(0.0, "up", "dash", "0"),
        ],
    )


def _bbwidth_panel(s: dict[str, pd.Series]) -> Panel:
    """Bant genisligi: sikisma (squeeze) ve genisleme donemlerini gosterir."""
    width = s["BB_width"]
    clean = width.dropna()
    # Sikisma esigi: gecmisin en dar %20'si. Sabit bir sayi her hissede
    # anlamli olmadigi icin serinin kendi dagilimindan turetiliyor.
    squeeze = float(clean.quantile(0.20)) if len(clean) else 0.0
    hlines = [HLine(squeeze, "accent2", "dash", "sıkışma")] if squeeze > 0 else []
    return Panel(
        key="bbwidth",
        title="Bant genişliği",
        height=0.65,
        traces=[Trace(name="Genişlik", y=width, color="accent1", width=1.4)],
        hlines=hlines,
    )


def _rvol_panel(s: dict[str, pd.Series]) -> Panel:
    """Bagil hacim: 1.0 = 20 barlik ortalamayla ayni hacim."""
    cap, exceeding = clip_outliers(s["RVOL"], quantile=0.97, headroom=1.15)
    return Panel(
        key="rvol",
        title="RVOL",
        params=f"{exceeding} bar kırpıldı" if exceeding else "",
        height=0.6,
        traces=[Trace(name="RVOL", y=s["RVOL"], color="accent2", width=1.4)],
        hlines=[HLine(2.0, "down", "dash", "2x"), HLine(1.0, "muted", "dash", "1x")],
        # Tek bir hacim patlamasi paneli duz cizgiye cevirmesin
        yrange=(0, max(cap, 3.0)) if np.isfinite(cap) else None,
    )



def _sar_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(name="Parabolic SAR", kind="dots", y=s["SAR"], color="#FDD835",
              width=2.4, zorder=4, tag=True)
    ]


def _keltner_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(name="Keltner 20/10/2", kind="band", y=s["KC_upper"], y2=s["KC_lower"],
              color="accent3", width=1.0, fill_alpha=0.06, zorder=1),
        Trace(name="KC orta", y=s["KC_mid"], color="accent3", width=1.0, dash="dot",
              legend=False, tag=True),
    ]


def _donchian_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    return [
        Trace(name="Donchian 20", kind="band", y=s["DC_upper"], y2=s["DC_lower"],
              color="accent1", width=1.1, fill_alpha=0.05, zorder=1),
        Trace(name="DC orta", y=s["DC_mid"], color="accent1", width=0.9, dash="dot",
              legend=False),
    ]


def _vprofile_overlays(s: dict[str, pd.Series]) -> list[Trace]:
    hist = s.get("VP_hist")
    if hist is None or len(hist) == 0:
        return []
    return [Trace(name="Hacim profili", kind="vprofile", y=hist, color="accent2",
                  fill_alpha=0.30, legend=False, zorder=0)]


def _cci_panel(s: dict[str, pd.Series]) -> Panel:
    upper = pd.Series(100.0, index=s["CCI"].index)
    lower = pd.Series(-100.0, index=s["CCI"].index)
    return Panel(
        key="cci", title="CCI", params="20", height=0.75,
        traces=[
            Trace(name="-100–100 bölgesi", kind="band", y=upper, y2=lower,
                  color="accent3", width=0, fill_alpha=0.08, legend=False, zorder=0),
            Trace(name="CCI", y=s["CCI"], color="accent3", width=1.4),
            Trace(name="CCI SMA 14", y=s["CCI_ma"], color="#FDD835", width=1.0),
            *_divergence_traces(s, "CCI"),
        ],
        hlines=[HLine(100, "down", "dash", "100"), HLine(-100, "up", "dash", "-100")],
        zero_line=True,
    )


def _willr_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="willr", title="Williams %R", params="14", height=0.7,
        traces=[Trace(name="%R", y=s["WILLR"], color="accent4", width=1.4)],
        hlines=[HLine(-20, "down", "dash", "-20"), HLine(-80, "up", "dash", "-80")],
        yrange=(-100, 0),
    )


def _ao_panel(s: dict[str, pd.Series]) -> Panel:
    ao = s["AO"]
    roles = pd.Series(np.where(ao.diff() >= 0, "up", "down"), index=ao.index)
    return Panel(
        key="ao", title="Awesome Oscillator", params="5, 34", height=0.7,
        traces=[Trace(name="AO", kind="hist", y=ao, colors=roles, legend=False)],
        zero_line=True,
    )


def _fisher_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="fisher", title="Fisher Dönüşümü", params="9", height=0.75,
        traces=[
            Trace(name="Fisher", y=s["FISHER"], color="accent3", width=1.5),
            Trace(name="Trigger", y=s["FISHER_trigger"], color="accent1", width=1.2),
            *_divergence_traces(s, "FISHER"),
        ],
        hlines=[
            HLine(1.5, "down", "dash", "1.5"), HLine(0.75, "muted", "dot", "0.75"),
            HLine(-0.75, "muted", "dot", "-0.75"), HLine(-1.5, "up", "dash", "-1.5"),
        ],
        zero_line=True,
    )


def _cmf_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="cmf", title="Chaikin Para Akışı", params="20", height=0.7,
        traces=[Trace(name="CMF", y=s["CMF"], color="#43A047", width=1.5), *_divergence_traces(s, "CMF")],
        zero_line=True,
        yrange=(-1, 1),
    )


def _momentum_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="momentum", title="Momentum", params="10", height=0.7,
        traces=[Trace(name="MOM", y=s["MOM"], color="accent3", width=1.5), *_divergence_traces(s, "MOM")],
        zero_line=True,
    )


def _atr_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="atr", title="ATR", params="14", height=0.65,
        traces=[Trace(name="ATR", y=s["ATR"], color="#B71C1C", width=1.4)],
    )


def _obv_panel(s: dict[str, pd.Series]) -> Panel:
    return Panel(
        key="obv", title="OBV", params="SMA 14 + BB 2", height=0.75,
        traces=[
            Trace(
                name="OBV bandı", kind="band", y=s["OBV_upper"], y2=s["OBV_lower"],
                color="#4CAF50", width=0.7, fill_alpha=0.08, legend=False,
            ),
            Trace(name="OBV", y=s["OBV"], color="accent3", width=1.4),
            Trace(name="OBV SMA", y=s["OBV_ma"], color="#FDD835", width=1.0),
            *_divergence_traces(s, "OBV"),
        ],
    )



def _kcpos_panel(df: pd.DataFrame, s: dict[str, pd.Series]) -> Panel:
    """Fiyatin Keltner kanali icindeki konumu (%).

    Kanali fiyat panelinde bant olarak cizmek yerine tek bir olcuye indirger;
    boylece mum grafigi tek gostergeye ayrilmis kalir.
    """
    span = (s["KC_upper"] - s["KC_lower"]).replace(0, np.nan)
    pos = 100.0 * (df["Close"] - s["KC_lower"]) / span
    return Panel(
        key="kcpos", title="Keltner konumu", params="20, 10, 2", height=0.7,
        traces=[Trace(name="Konum %", y=pos, color="accent3", width=1.4)],
        hlines=[HLine(100, "down", "dash", "üst"), HLine(50, "muted", "dot", "orta"),
                HLine(0, "up", "dash", "alt")],
    )


def _dcpos_panel(df: pd.DataFrame, s: dict[str, pd.Series]) -> Panel:
    """Fiyatin Donchian kanali icindeki konumu (%). 100 = yeni zirve."""
    span = (s["DC_upper"] - s["DC_lower"]).replace(0, np.nan)
    pos = 100.0 * (df["Close"] - s["DC_lower"]) / span
    return Panel(
        key="dcpos", title="Donchian konumu", params="20", height=0.7,
        traces=[Trace(name="Konum %", y=pos, color="accent1", width=1.4)],
        hlines=[HLine(100, "down", "dash", "zirve"), HLine(0, "up", "dash", "dip")],
        yrange=(-5, 105),
    )


def _vwapdev_panel(df: pd.DataFrame, s: dict[str, pd.Series]) -> Panel:
    """Fiyatin VWAP'tan yuzde sapmasi. Sifir = hacim agirlikli adil deger."""
    dev = 100.0 * (df["Close"] / s["VWAP"].replace(0, np.nan) - 1.0)
    return Panel(
        key="vwapdev", title="VWAP sapması", params="%", height=0.7,
        traces=[Trace(name="Sapma %", y=dev, color="vwap", width=1.4)],
        zero_line=True,
    )


def _bbands_panel(df: pd.DataFrame, s: dict[str, pd.Series]) -> Panel:
    """Bollinger %B + sikisma esigi tek panelde."""
    width = s["BB_width"]
    clean = width.dropna()
    squeeze = float(clean.quantile(0.20)) if len(clean) else 0.0
    scale = float(clean.max()) if len(clean) else 1.0
    normalized = width / scale * 100.0 if scale else width
    return Panel(
        key="bbpanel", title="Bollinger %B", params="20, 2", height=0.75,
        traces=[
            Trace(name="%B", y=s["BB_percent_b"] * 100.0, color="accent3", width=1.4),
            Trace(name="Genişlik", y=normalized, color="accent1", width=0.9, dash="dot"),
        ],
        hlines=[HLine(100, "down", "dash", "üst"), HLine(0, "up", "dash", "alt")]
        + ([HLine(squeeze / scale * 100.0, "accent2", "dot", "sıkışma")] if scale else []),
    )


_OVERLAY_BUILDERS = {
    "candles": lambda df, s: _candlestick_overlays(s),
    "ma": lambda df, s: _ma_overlays(s),
    "bbands": lambda df, s: _bb_overlays(s),
    "supertrend": lambda df, s: _supertrend_overlays(s),
    "ichimoku": lambda df, s: _ichimoku_overlays(s),
    "vwap": lambda df, s: _vwap_overlays(s),
    "sar": lambda df, s: _sar_overlays(s),
    "keltner": lambda df, s: _keltner_overlays(s),
    "donchian": lambda df, s: _donchian_overlays(s),
    "vprofile": lambda df, s: _vprofile_overlays(s),
}

_PANEL_BUILDERS = {
    "volume": lambda df, s: _volume_panel(df, s),
    "rsi": lambda df, s: _rsi_panel(s),
    "macd": lambda df, s: _macd_panel(s),
    "smi": lambda df, s: _smi_panel(s),
    "stochrsi": lambda df, s: _stochrsi_panel(s),
    "adx": lambda df, s: _adx_panel(s),
    "bbstate": lambda df, s: _bbstate_panel(s),
    "bbwidth": lambda df, s: _bbwidth_panel(s),
    "rvol": lambda df, s: _rvol_panel(s),
    "cci": lambda df, s: _cci_panel(s),
    "willr": lambda df, s: _willr_panel(s),
    "ao": lambda df, s: _ao_panel(s),
    "fisher": lambda df, s: _fisher_panel(s),
    "cmf": lambda df, s: _cmf_panel(s),
    "momentum": lambda df, s: _momentum_panel(s),
    "atr": lambda df, s: _atr_panel(s),
    "obv": lambda df, s: _obv_panel(s),
    "kcpos": lambda df, s: _kcpos_panel(df, s),
    "dcpos": lambda df, s: _dcpos_panel(df, s),
    "vwapdev": lambda df, s: _vwapdev_panel(df, s),
    "bbpanel": lambda df, s: _bbands_panel(df, s),
}

#: Cizim anahtari -> ihtiyac duydugu hesap anahtari.
#: Bir gorunum yalnizca kullandigi gostergeleri hesaplatsin diye gerekli.
REQUIRES: dict[str, tuple[str, ...]] = {
    "candles": ("candles",),
    "ma": ("ma",),
    "bbands": ("bbands",),
    "supertrend": ("supertrend",),
    "ichimoku": ("ichimoku",),
    "vwap": ("vwap",),
    "volume": ("volume",),
    "rsi": ("rsi",),
    "macd": ("macd",),
    "smi": ("smi",),
    "stochrsi": ("stochrsi",),
    "adx": ("adx",),
    "bbstate": ("bbands",),
    "bbwidth": ("bbands",),
    "rvol": ("volume",),
    "sar": ("sar",),
    "keltner": ("keltner",),
    "donchian": ("donchian",),
    "vprofile": ("vprofile",),
    "cci": ("cci",),
    "willr": ("willr",),
    "ao": ("ao",),
    "fisher": ("fisher",),
    "cmf": ("cmf",),
    "momentum": ("momentum",),
    "atr": ("atr",),
    "obv": ("obv",),
    "kcpos": ("keltner",),
    "dcpos": ("donchian",),
    "vwapdev": ("vwap",),
    "bbpanel": ("bbands",),
}


def compute_keys_for(draw_keys: tuple[str, ...]) -> tuple[str, ...]:
    """Cizilecek katmanlarin gerektirdigi hesap anahtarlarini sirali dondurur."""
    out: list[str] = []
    for key in draw_keys:
        for required in REQUIRES.get(key, (key,)):
            if required not in out:
                out.append(required)
    return tuple(out)


# --------------------------------------------------------------------------
# Ozet serit
# --------------------------------------------------------------------------


def _fmt(value: float, digits: int = 2) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "—"
    return f"{value:,.{digits}f}".replace(",", " ")


def _last(series: pd.Series | None) -> float:
    if series is None:
        return float("nan")
    clean = series.dropna()
    return float(clean.iloc[-1]) if len(clean) else float("nan")


def build_snapshot(df: pd.DataFrame, s: dict[str, pd.Series]) -> list[tuple[str, str, str]]:
    """Baslikta gosterilecek durum rozetleri."""
    chips: list[tuple[str, str, str]] = []
    # Grafik ileri dogru uzatilmis olabilir (Ichimoku projeksiyonu): bu barlarda
    # fiyat NaN'dir, ozet her zaman son GERCEK bardan okunmalidir.
    closes = df["Close"].dropna()
    if len(closes) == 0:
        return chips
    close = float(closes.iloc[-1])
    prev = float(closes.iloc[-2]) if len(closes) > 1 else close
    change = (close / prev - 1.0) * 100.0 if prev else 0.0
    chips.append(("Son", _fmt(close), "up" if change >= 0 else "down"))
    chips.append(("Değişim", f"{change:+.2f}%", "up" if change >= 0 else "down"))

    if "RSI" in s:
        value = _last(s["RSI"])
        role = "down" if value >= 70 else "up" if value <= 30 else "neutral"
        chips.append(("RSI", _fmt(value, 1), role))
    if "MACD_hist" in s:
        value = _last(s["MACD_hist"])
        chips.append(("MACD hist", _fmt(value, 3), "up" if value >= 0 else "down"))
    if "ADX" in s:
        value = _last(s["ADX"])
        role = "accent1" if value >= 25 else "muted"
        chips.append(("ADX", _fmt(value, 1), role))
    if "ST_dir" in s:
        direction = _last(s["ST_dir"])
        chips.append(
            ("Supertrend", "yukarı" if direction > 0 else "aşağı", "up" if direction > 0 else "down")
        )
    if "BB_percent_b" in s:
        chips.append(("%B", _fmt(_last(s["BB_percent_b"]), 2), "neutral"))
    if "RVOL" in s:
        value = _last(s["RVOL"])
        chips.append(("RVOL", f"{value:.2f}x" if np.isfinite(value) else "—", "accent1" if value >= 1.5 else "neutral"))
    return chips


def needs_log_scale(df: pd.DataFrame, ratio: float = 4.0) -> bool:
    """Fiyat araligi cok genisse logaritmik olcek gerekir.

    100'den 700'e cikan bir seride lineer eksende ilk aylardaki hareketler
    ezilir ve mumlar okunamaz hale gelir. Oran esigi asildiginda log'a gecilir.
    """
    prices = df["Low"].dropna()
    highs = df["High"].dropna()
    if len(prices) == 0 or len(highs) == 0:
        return False
    low = float(prices[prices > 0].min()) if (prices > 0).any() else 0.0
    high = float(highs.max())
    return low > 0 and high / low >= ratio


def build_spec(
    df: pd.DataFrame,
    series: dict[str, pd.Series],
    keys: tuple[str, ...],
    title: str,
    subtitle: str,
    price_height: float = 3.4,
    panel_scale: float = 1.0,
    note: str = "",
    last_bar_open: bool = False,
    log_price: bool | None = None,
) -> ChartSpec:
    overlays: list[Trace] = []
    panels: list[Panel] = []
    for key in keys:
        if key in _OVERLAY_BUILDERS:
            overlays.extend(_OVERLAY_BUILDERS[key](df, series))
        elif key in _PANEL_BUILDERS:
            panel = _PANEL_BUILDERS[key](df, series)
            panel.height *= panel_scale
            panels.append(panel)
    return ChartSpec(
        df=df,
        overlays=overlays,
        panels=panels,
        title=title,
        subtitle=subtitle,
        snapshot=build_snapshot(df, series),
        price_height=price_height,
        note=note,
        last_bar_open=last_bar_open,
        log_price=needs_log_scale(df) if log_price is None else log_price,
    )


def segment_ranges(colors: pd.Series) -> list[tuple[int, int, str]]:
    """Ardisik ayni renkli bolgeleri (baslangic, bitis, rol) olarak dondurur.

    Supertrend gibi renk degistiren cizgileri iki arka ucta da ayni sekilde
    parcalamak icin kullanilir.
    """
    values = list(colors)
    out: list[tuple[int, int, str]] = []
    start = None
    current = None
    for i, role in enumerate(values):
        role = role if isinstance(role, str) else None
        if role != current:
            if current is not None and start is not None and i - start >= 1:
                out.append((start, i, current))
            start, current = i, role
    if current is not None and start is not None:
        out.append((start, len(values), current))
    return [(a, b, r) for a, b, r in out if r]
