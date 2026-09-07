"""Takip listesi ve seviye uyarıları.

Takibe alınan sembolde eşikler, referans alınan son teyitli kapanışın iki
yanındaki teyit edilmiş piyasa yapısı seviyelerinden seçilir. Böylece daha
önce kırılmış bir swing dip, fiyatın üzerinde kaldığı halde "alt eşik" olarak
kaydedilemez; rolü varsa yukarı reclaim seviyesi olarak değerlendirilir.

Uyarılar yalnızca tamamlanmış mum kapanışlarıyla değerlendirilir ve yalnızca
seviye geçişinde üretilir. Fiyat eşik dışında kalmaya devam ederken aynı uyarı
tekrarlanmaz; fiyat yeniden eşiğin öteki tarafına döndükten sonra yeni bir
kapanış geçişi oluşursa uyarı yeniden kurulmuş sayılır. Uyarı, eşiğin
aşıldığını bildirir; ne yapılması gerektiğini söylemez.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.bar_state import build_bar_state

WATCH_PATH = Path("reports/watchlist.json")
MAX_WATCHED = 20
PIVOT_LEFT = 5
PIVOT_RIGHT = 5
FALLBACK_RANGE_BARS = 20


@dataclass
class Watch:
    ticker: str
    interval: str
    upper: float
    lower: float
    setup: str
    added_at: str
    # Geriye dönük uyumluluk için tutulur; artık kalıcı kilit değildir.
    # bot_runner bu alana yalnız son uyarı zamanını yazar.
    triggered: str = ""
    reference_close: float = math.nan
    lower_source: str = ""
    upper_source: str = ""
    reference_bar: str = ""
    last_checked_bar: str = ""
    # Eski watch JSON kayıtlarında bu alan yoktur. None, "henüz güvenilir bir
    # önceki kapanış gözlemi yok" anlamına gelir ve ilk gözlemde sahte uyarıyı
    # önler.
    last_close: float | None = None
    # inside / above / below. Ayrı durum tutulması aynı yönde spam'i önler ve
    # fiyat banda döndükten sonra yeni crossing için uyarının yeniden kurulmasını
    # açık ve kalıcı hale getirir.
    alert_state: str = ""
    # Geriye dönük görünürlük için son olay yönü; karar mantığı alert_state'tedir.
    last_event: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _state_for_close(close: float, lower: float, upper: float) -> str:
    if close > upper:
        return "above"
    if close < lower:
        return "below"
    return "inside"


def confirmed_frame(
    data: pd.DataFrame,
    market: str,
    interval: str,
    now: datetime | None = None,
) -> pd.DataFrame:
    """Yalnızca tamamlanmış mumları döndürür."""
    if data.empty:
        raise ValueError("Takip seviyesi için fiyat verisi boş.")
    state = build_bar_state(data, market, interval, now=now)
    confirmed = data.iloc[:-1] if state["is_live"] else data
    if confirmed.empty:
        raise ValueError("Henüz teyit edilmiş mum bulunmuyor.")
    return confirmed


def latest_confirmed_close(
    data: pd.DataFrame,
    market: str,
    interval: str,
    now: datetime | None = None,
) -> tuple[float, str]:
    """Son tamamlanmış mumun kapanışını ve zamanını döndürür."""
    confirmed = confirmed_frame(data, market, interval, now=now)
    close = _finite(confirmed["Close"].iloc[-1])
    if close is None:
        raise ValueError("Son teyitli mum kapanışı geçerli değil.")
    return close, pd.Timestamp(confirmed.index[-1]).isoformat()


def _confirmed_pivot_candidates(data: pd.DataFrame) -> list[tuple[float, str, int]]:
    """5+5 teyitli swing seviyelerini fiyat, tür ve bar sırası ile çıkarır."""
    highs = data["High"].to_numpy(dtype=float)
    lows = data["Low"].to_numpy(dtype=float)
    candidates: list[tuple[float, str, int]] = []
    for index in range(PIVOT_LEFT, len(data) - PIVOT_RIGHT):
        high_window = highs[index - PIVOT_LEFT : index + PIVOT_RIGHT + 1]
        low_window = lows[index - PIVOT_LEFT : index + PIVOT_RIGHT + 1]
        if math.isfinite(highs[index]) and highs[index] == max(high_window):
            candidates.append((float(highs[index]), "swing_high", index))
        if math.isfinite(lows[index]) and lows[index] == min(low_window):
            candidates.append((float(lows[index]), "swing_low", index))
    return candidates


def _source_label(kind: str, level: float, reference: float) -> str:
    if kind == "swing_low":
        return "Teyitli swing dip" if level < reference else "Kırılmış swing dip / reclaim"
    if kind == "swing_high":
        return "Kırılmış swing tepe / destek" if level < reference else "Teyitli swing tepe"
    return kind


def select_watch_levels(
    data: pd.DataFrame,
    market: str,
    interval: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Referans kapanışın iki yanında geçerli takip seviyelerini seçer.

    Öncelik teyitli swing pivotlarındadır. Bir tarafta teyitli pivot yoksa son
    20 tamamlanmış barın fiyat sınırı yalnızca yedek seviye olarak kullanılır.
    Çıktının temel invariantı ``lower < reference_close < upper`` şeklindedir.
    """
    confirmed = confirmed_frame(data, market, interval, now=now)
    reference = _finite(confirmed["Close"].iloc[-1])
    if reference is None or reference <= 0:
        raise ValueError("Takip için geçerli teyitli kapanış bulunamadı.")

    pivots = _confirmed_pivot_candidates(confirmed)
    below = [item for item in pivots if item[0] < reference]
    above = [item for item in pivots if item[0] > reference]

    # Aynı fiyatta birden fazla pivot varsa daha yeni olanı tercih ederiz.
    lower_item = max(below, key=lambda item: (item[0], item[2])) if below else None
    upper_item = min(above, key=lambda item: (item[0], -item[2])) if above else None

    window = confirmed.tail(FALLBACK_RANGE_BARS)
    if lower_item is None:
        fallback_low = _finite(window["Low"].min())
        if fallback_low is not None and fallback_low < reference:
            lower_item = (fallback_low, f"Son {len(window)} bar alt sınırı", len(confirmed) - 1)
    if upper_item is None:
        fallback_high = _finite(window["High"].max())
        if fallback_high is not None and fallback_high > reference:
            upper_item = (fallback_high, f"Son {len(window)} bar üst sınırı", len(confirmed) - 1)

    if lower_item is None or upper_item is None:
        raise ValueError(
            "Referans kapanışın hem altında hem üstünde güvenilir teyitli seviye bulunamadı; "
            "takip kaydı oluşturulmadı."
        )

    lower = float(lower_item[0])
    upper = float(upper_item[0])
    if not lower < reference < upper:
        raise ValueError(
            f"Takip seviyesi çelişkili: {lower:.2f} < {reference:.2f} < {upper:.2f} koşulu sağlanmıyor."
        )

    lower_source = (
        _source_label(lower_item[1], lower, reference)
        if lower_item[1] in {"swing_low", "swing_high"}
        else lower_item[1]
    )
    upper_source = (
        _source_label(upper_item[1], upper, reference)
        if upper_item[1] in {"swing_low", "swing_high"}
        else upper_item[1]
    )
    return {
        "reference_close": reference,
        "reference_bar": pd.Timestamp(confirmed.index[-1]).isoformat(),
        "lower": lower,
        "upper": upper,
        "lower_source": lower_source,
        "upper_source": upper_source,
    }


def load_watches(path: Path = WATCH_PATH) -> dict[str, Watch]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}

    watches: dict[str, Watch] = {}
    for ticker, item in payload.items():
        try:
            raw_last_close = item.get("last_close")
            last_close = _finite(raw_last_close) if raw_last_close is not None else None
            watches[str(ticker)] = Watch(
                ticker=str(item["ticker"]),
                interval=str(item.get("interval", "1d")),
                upper=float(item["upper"]),
                lower=float(item["lower"]),
                setup=str(item.get("setup", "")),
                added_at=str(item.get("added_at", "")),
                triggered=str(item.get("triggered", "")),
                reference_close=float(item.get("reference_close", math.nan)),
                lower_source=str(item.get("lower_source", "")),
                upper_source=str(item.get("upper_source", "")),
                reference_bar=str(item.get("reference_bar", "")),
                last_checked_bar=str(item.get("last_checked_bar", "")),
                last_close=last_close,
                alert_state=str(item.get("alert_state", "")),
                last_event=str(item.get("last_event", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return watches


def save_watches(watches: dict[str, Watch], path: Path = WATCH_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({ticker: watch.as_dict() for ticker, watch in watches.items()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def add_watch(watches: dict[str, Watch], watch: Watch) -> tuple[dict[str, Watch] | None, str]:
    reference = _finite(watch.reference_close)
    if reference is not None and not watch.lower < reference < watch.upper:
        return None, (
            f"{watch.ticker} için takip oluşturulmadı: eşikler referans kapanışı çevrelemiyor "
            f"({watch.lower:,.2f} < {reference:,.2f} < {watch.upper:,.2f})."
        )
    if reference is not None and _finite(watch.last_close) is None:
        watch.last_close = reference
    if _finite(watch.last_close) is not None and not watch.alert_state:
        watch.alert_state = _state_for_close(float(watch.last_close), watch.lower, watch.upper)

    if watch.ticker in watches:
        updated = dict(watches)
        updated[watch.ticker] = watch
        reference_text = "—" if reference is None else f"{reference:,.2f}"
        return updated, (
            f"{watch.ticker} takip seviyeleri güncellendi.\n"
            f"Referans teyitli kapanış: {reference_text}\n"
            f"Alt eşik: {watch.lower:,.2f} — {watch.lower_source or 'yapısal seviye'}\n"
            f"Üst eşik: {watch.upper:,.2f} — {watch.upper_source or 'yapısal seviye'}"
        )
    if len(watches) >= MAX_WATCHED:
        return None, f"Takip listesi dolu (en fazla {MAX_WATCHED}). Önce /takip sil SEMBOL ile yer açın."

    updated = dict(watches)
    updated[watch.ticker] = watch
    reference_text = "—" if reference is None else f"{reference:,.2f}"
    return updated, (
        f"{watch.ticker} takibe alındı ({watch.interval}).\n"
        f"Referans teyitli kapanış: {reference_text}\n"
        f"Alt eşik: {watch.lower:,.2f} — {watch.lower_source or 'yapısal seviye'}\n"
        f"Üst eşik: {watch.upper:,.2f} — {watch.upper_source or 'yapısal seviye'}\n"
        f"Uyarı yalnızca tamamlanmış {watch.interval} mum kapanışıyla ve yeni eşik geçişinde verilir."
    )


def remove_watch(watches: dict[str, Watch], ticker: str) -> tuple[dict[str, Watch] | None, str]:
    symbol = ticker.strip().upper()
    if symbol not in watches:
        return None, f"{symbol} takip listesinde yok."
    updated = dict(watches)
    updated.pop(symbol)
    return updated, f"{symbol} takipten çıkarıldı."


def describe(watches: dict[str, Watch]) -> str:
    if not watches:
        return "Takip listesi boş. Eklemek için: /takip THYAO"
    lines = [f"Takip listesi ({len(watches)}/{MAX_WATCHED}):"]
    for watch in watches.values():
        state = f" — son uyarı {watch.triggered}" if watch.triggered else ""
        reference = _finite(watch.reference_close)
        reference_text = f" | ref {reference:,.2f}" if reference is not None else ""
        lines.append(
            f"{watch.ticker} ({watch.interval}): {watch.lower:,.2f} – {watch.upper:,.2f}{reference_text}{state}"
        )
    lines.append("")
    lines.append("Çıkarmak için: /takip sil THYAO")
    return "\n".join(lines)


def check_break(watch: Watch, close: float) -> str:
    """Yeni teyitli kapanışta gerçek eşik geçişi varsa uyarı metnini döndürür.

    Eski kayıtta ``last_close`` yoksa ilk gözlem yalnız başlangıç durumu olarak
    kaydedilir; geçmişte gerçekleşmiş bir kırılımı yeniymiş gibi bildirmez.
    Yeni kayıtlarda ise referans kapanış başlangıç noktasıdır. Fiyat eşik
    dışında kaldıkça tekrar uyarı üretilmez; banda döndükten sonraki yeni
    crossing tekrar bildirilebilir.
    """
    current = _finite(close)
    if current is None:
        return ""

    previous = _finite(watch.last_close)
    if previous is None:
        watch.last_close = current
        watch.alert_state = _state_for_close(current, watch.lower, watch.upper)
        watch.last_event = ""
        return ""

    previous_state = watch.alert_state or _state_for_close(previous, watch.lower, watch.upper)
    current_state = _state_for_close(current, watch.lower, watch.upper)
    watch.last_close = current
    watch.alert_state = current_state

    if previous_state != "above" and current_state == "above" and previous <= watch.upper < current:
        watch.last_event = "upper"
        return (
            f"🔔 {watch.ticker} — yukarı eşik aşıldı\n"
            f"Teyitli kapanış {current:,.2f}, izlenen üst seviye {watch.upper:,.2f}.\n"
            f"Önceki teyitli kapanış: {previous:,.2f}.\n"
            f"Seviye kaynağı: {watch.upper_source or 'yapısal seviye'}.\n"
            f"Takibe alındığındaki kurulum: {watch.setup or '—'}.\n"
            "Bu bir alım/satım önerisi değildir; yalnızca izlenen seviyenin aşıldığını bildirir."
        )
    if previous_state != "below" and current_state == "below" and previous >= watch.lower > current:
        watch.last_event = "lower"
        return (
            f"🔔 {watch.ticker} — aşağı eşik aşıldı\n"
            f"Teyitli kapanış {current:,.2f}, izlenen alt seviye {watch.lower:,.2f}.\n"
            f"Önceki teyitli kapanış: {previous:,.2f}.\n"
            f"Seviye kaynağı: {watch.lower_source or 'yapısal seviye'}.\n"
            f"Takibe alındığındaki kurulum: {watch.setup or '—'}.\n"
            "Bu bir alım/satım önerisi değildir; yalnızca izlenen seviyenin aşıldığını bildirir."
        )

    if current_state == "inside":
        watch.last_event = ""
    return ""
