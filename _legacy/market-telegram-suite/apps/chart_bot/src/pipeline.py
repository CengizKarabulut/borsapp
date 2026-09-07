"""Uctan uca akis: veri -> gosterge -> cizim tarifi.

CLI ve testler bu modulu kullanir; cizim arka uclari (PNG/HTML) yalnizca
buradan cikan ChartSpec'i tuketir.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from . import indicators as ind
from . import format as fmt
from .data_sources import SymbolSpec, fetch_ohlcv
from .views import VIEWS_BY_KEY, View
from .plotspec import ChartSpec, build_spec, compute_keys_for

INTERVAL_LABELS = {
    "1m": "1 dakika",
    "5m": "5 dakika",
    "15m": "15 dakika",
    "30m": "30 dakika",
    "1h": "1 saat",
    "2h": "2 saat",
    "3h": "3 saat",
    "4h": "4 saat",
    "1d": "günlük",
    "1wk": "haftalık",
    "1mo": "aylık",
}

#: Aralik basina makul bar sayisi. Sabit 250 kullanilirsa aylik grafikte
#: 20 yillik gecmis sikisir ve mumlar bir piksele iner; haftalikta da benzer
#: sorun olur. Kullanici --bars verirse bu tablo devre disi kalir.
DEFAULT_BARS: dict[str, int] = {
    "1m": 180, "5m": 200, "15m": 220, "30m": 240,
    "1h": 250, "2h": 250, "3h": 250, "4h": 250,
    "1d": 170, "1wk": 130, "1mo": 96,
}


def default_bars(interval: str) -> int:
    return DEFAULT_BARS.get(interval, 250)


#: Periyot secilmediginde araliga gore makul bir varsayilan
DEFAULT_PERIODS = {
    "1m": "5d",
    "5m": "1mo",
    "15m": "1mo",
    "30m": "3mo",
    "1h": "6mo",
    "2h": "1y",
    "3h": "1y",
    # 4 saatlik barlar saatlikten turetildigi icin saatlik gecmis cekilir;
    # yfinance saatlik veride 2 yildan eskiye izin vermez.
    "4h": "2y",
    "1d": "2y",
    "1wk": "5y",
    "1mo": "10y",
}


INTRADAY = {"1m", "5m", "15m", "30m", "1h", "2h", "4h"}


def default_params(interval: str, params: dict[str, dict] | None = None) -> dict[str, dict]:
    """Araliga gore gosterge varsayilanlarini secer.

    VWAP Auto Anchored, TradingView'in resmi zaman araligi kuralini izler:
    gun icinde son seans, gunlukte son ay, haftalikta son ceyrek ve aylikta
    son yil baslangicindan itibaren hesaplanir.
    """
    merged: dict[str, dict] = {
        "vwap": {"anchor": "auto", "interval": interval, "window": 14}
    }
    for key, value in (params or {}).items():
        merged[key] = {**merged.get(key, {}), **value}
    return merged


#: Piyasa -> seans kapanis saati (saat, dakika). None = 7/24 (kripto).
#: Gunluk ve ustu barlarda bar suresi yaniltici olur: BIST gunluk bari 09:00
#: damgasini tasir ama seans 18:00'de biter. Sadece sureye bakilirsa bar
#: ertesi sabaha kadar "acik" gorunur.
SESSION_END: dict[str, tuple[int, int] | None] = {
    "bist": (18, 15),
    "equity": (16, 15),
    "crypto": None,
}


def last_bar_is_open(
    index: pd.DatetimeIndex,
    now: pd.Timestamp | None = None,
    market: str = "bist",
) -> bool:
    """Son bar hala olusuyor mu?

    Gun ici barlarda bar suresi yeterlidir: son barin baslangicina sure
    eklendiginde gelecekte kaliyorsa bar kapanmamistir.

    Gunluk ve ustu barlarda ayrica SEANS KAPANISI dikkate alinir. BIST gunluk
    bari 09:00 damgasi tasir; yalnizca sureye bakilsa bar ertesi sabah 09:00'a
    kadar acik sayilir ve seans bittikten sonra bile yanlis uyari verir.

    Onemli: acik bir barda RVOL, RSI ve gunluk degisim gun kapaninca degisir.
    Bunu isaretlemezsek grafik yaniltici olur.
    """
    if len(index) < 3:
        return False
    now = now or pd.Timestamp.now()
    deltas = pd.Series(index[1:]) - pd.Series(index[:-1])
    step = deltas.median()
    if pd.isna(step) or step <= pd.Timedelta(0):
        return False

    start = index[-1]
    if now >= start + step:
        return False

    session = SESSION_END.get(market, SESSION_END["bist"])
    if step < pd.Timedelta(days=1) or session is None:
        return True  # gun ici ya da 7/24 piyasa: sure yeterli

    # Barin kapsadigi son islem gunu: sure sonundan bir gun geri, hafta sonu
    # denk gelirse cumaya cekilir (haftalik barda cuma kapanisi gecerlidir).
    last_day = (start + step - pd.Timedelta(days=1)).normalize()
    while last_day.weekday() >= 5:
        last_day -= pd.Timedelta(days=1)
    close_time = last_day + pd.Timedelta(hours=session[0], minutes=session[1])
    return bool(now < close_time)


def _future_index(index: pd.DatetimeIndex, bars: int) -> pd.DatetimeIndex:
    """Mevcut barlarin ritmini surdurerek ileriye dogru bos zaman damgasi uretir."""
    if len(index) < 3 or bars <= 0:
        return pd.DatetimeIndex([])
    deltas = pd.Series(index[1:]) - pd.Series(index[:-1])
    step = deltas.median()
    daily_or_higher = step >= pd.Timedelta(days=1)
    out: list[pd.Timestamp] = []
    cursor = index[-1]
    while len(out) < bars:
        cursor = cursor + step
        if daily_or_higher and step < pd.Timedelta(days=6) and cursor.weekday() >= 5:
            continue  # gunluk grafikte hafta sonu etiketi uretme
        out.append(cursor)
    return pd.DatetimeIndex(out)


def extend_future(
    df: pd.DataFrame, series: dict[str, pd.Series], bars: int
) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    """Ichimoku bulutunu fiyatin onune tasimak icin grafigi saga uzatir.

    Fiyat barlari bos (NaN) kalir, yalnizca kaydirilmis Senkou A/B degerleri
    doldurulur. TradingView'daki "bulut fiyattan once biter" gorunumu boyle
    elde edilir.
    """
    if bars <= 0 or "ICH_span_a_raw" not in series:
        return df, series

    future = _future_index(df.index, bars)
    if len(future) == 0:
        return df, series

    new_index = df.index.append(future)
    df_ext = df.reindex(new_index)
    # Fiyat eksenli seriler (VP_hist) zaman indeksine sahip degil, dokunulmaz
    ext = {k: (v if k.startswith("VP_") else v.reindex(new_index))
           for k, v in series.items()}

    n = len(df.index)
    for span, raw in (("ICH_span_a", "ICH_span_a_raw"), ("ICH_span_b", "ICH_span_b_raw")):
        tail = series[raw].to_numpy(dtype="float64")[-bars:]
        values = ext[span].to_numpy(dtype="float64").copy()
        values[n : n + len(tail)] = tail[: len(values) - n]
        ext[span] = pd.Series(values, index=new_index)
    return df_ext, ext


@dataclass
class ChartResult:
    """Tek bir gorunumun cizime hazir hali."""

    view: View
    spec: ChartSpec

    @property
    def key(self) -> str:
        return self.view.key


@dataclass
class ViewSet:
    """Bir sembol/aralik icin uretilen tum gorunumler."""

    symbol: SymbolSpec
    interval: str
    results: list[ChartResult]
    source_label: str
    generated_at: str
    subtitle: str

    def __iter__(self):
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)


def build_views(
    symbol: str,
    views: tuple[View, ...],
    interval: str = "1d",
    bars: int = 250,
    period: str | None = None,
    params: dict[str, dict] | None = None,
    project_bars: int | None = None,
    log_price: bool | None = None,
) -> ViewSet:
    """Tum gorunumleri TEK veri cekimi ve TEK hesap turuyla uretir.

    Gorunumler ayni seriyi paylastigi icin ortak gostergeler (orn. birden fazla
    karede gecen hareketli ortalamalar) yalnizca bir kez hesaplanir.
    """
    if not views:
        raise ValueError("En az bir gorunum gerekli")

    period = period or DEFAULT_PERIODS.get(interval, "2y")
    params = default_params(interval, params)

    needed: list[str] = []
    for view in views:
        for key in view.compute_keys:
            if key not in needed:
                needed.append(key)

    # Gostergeler once TUM gecmis uzerinde hesaplanir, kirpma sonra yapilir;
    # aksi halde EMA200 gibi uzun periyotlar grafigin sol yarisinda bos kalirdi.
    df_full, symbol_spec = fetch_ohlcv(symbol, period=period, interval=interval)

    temporal = tuple(k for k in needed if k not in ind.NON_TEMPORAL)
    series_full = ind.compute(df_full, keys=temporal, params=params)

    df_window = df_full.tail(bars)
    series_window = {k: v.reindex(df_window.index) for k, v in series_full.items()}

    # Hacim profili gibi fiyat eksenli gostergeler GORUNEN pencereden hesaplanir;
    # tum gecmisten hesaplanip kirpilirsa profil ekrandaki barlarla uyusmaz.
    for key in needed:
        if key in ind.NON_TEMPORAL:
            series_window.update(ind.compute(df_window, keys=(key,), params=params))

    interval_label = INTERVAL_LABELS.get(interval, interval)
    last_ts = df_full.index[-1]
    bar_open = last_bar_is_open(df_full.index, market=symbol_spec.market)
    subtitle = (
        f"{interval_label} · {len(df_window)} bar · son bar "
        f"{fmt.tam_tarih(last_ts)}" + (" · SON BAR AÇIK" if bar_open else "")
    )

    # Izgarada karolarin x eksenleri hizali dursun diye projeksiyon payi TUM
    # karelere ayni sekilde uygulanir; yalnizca Ichimoku'lu kare uzatilsaydi
    # o karo digerlerinden daha genis bir zaman araligi gosterirdi.
    any_cloud = any("ichimoku" in v.keys for v in views)
    ahead = (25 if any_cloud else 0) if project_bars is None else (
        project_bars if any_cloud else 0
    )

    results: list[ChartResult] = []
    for view in views:
        df_view, series_view = extend_future(df_window, series_window, ahead)
        results.append(
            ChartResult(
                view=view,
                spec=build_spec(
                    df=df_view,
                    series=series_view,
                    keys=view.keys,
                    title=f"{symbol_spec.display} · {view.title}",
                    subtitle=subtitle,
                    note=view.note,
                    price_height=view.price_height,
                    panel_scale=view.panel_scale,
                    last_bar_open=bar_open,
                    log_price=log_price,
                ),
            )
        )

    return ViewSet(
        symbol=symbol_spec,
        interval=interval,
        results=results,
        source_label=symbol_spec.provider,
        generated_at=datetime.now().strftime("%d.%m.%Y %H:%M"),
        subtitle=subtitle,
    )


def build_chart(
    symbol: str,
    interval: str = "1d",
    bars: int = 250,
    period: str | None = None,
    keys: tuple[str, ...] = ind.ALL_INDICATORS,
    params: dict[str, dict] | None = None,
    project_bars: int | None = None,
    log_price: bool | None = None,
) -> ViewSet:
    """Serbest gosterge listesini tek bir gorunum gibi uretir."""
    view = View(
        key="ozel",
        title="Seçili göstergeler",
        keys=keys,
        note=", ".join(keys),
        price_height=3.4,
        panel_scale=1.0,
    )
    return build_views(
        symbol, (view,), interval=interval, bars=bars, period=period,
        params=params, project_bars=project_bars, log_price=log_price,
    )
