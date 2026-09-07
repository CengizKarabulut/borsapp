"""BIST geneli teknik tarayıcı.

600+ sembol için iki aşamalı çalışır:

1. Ucuz aşama: yalnızca gösterge hesabı (~135 ms/sembol). Likidite ve temel
   filtreler burada uygulanır.
2. Pahalı aşama: yalnızca ilk aşamayı geçen sembollerde yapı, hacim profili,
   uyumsuzluk ve kurulum tanıma çalıştırılır (~850 ms/sembol).

Bu ayrım olmadan 600 sembol tek başına 8+ dakika CPU harcar. Tarama sonucu her
durumda raporlanır; eşleşme çıkmasa veya semboller hata verse bile özet
gönderilir, böylece sessiz başarısızlık oluşmaz.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from src.divergence import detect_divergences
from src.market_context import market_structure, profile_context
from src.semantic_features import build_semantic_features
from src.setup_recognition import build_setup_context
from src.stock_dashboard import MA_PERIODS, calculate_indicators

BATCH_SIZE = 40
# Zaman dilimlerini kısadan uzuna sıralamak için; birleşik listede görünen
# değerler en kısa (en güncel) dilimden alınır.
INTERVAL_ORDER = {"5m": 1, "15m": 2, "30m": 3, "1h": 4, "2h": 5, "4h": 6, "1d": 7, "1wk": 8, "1mo": 9}


def _number(value: Any, default: float = math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


# Hata sınıfları: veri yetersizliği gerçek arıza değildir; 600 sembolde yüzlerce
# yeni halka arz ve hisse olmayan kayıt bu gruba düşer ve asıl arızaları gizler.
ERROR_KINDS = {
    "kisa_gecmis": ("bar gerekli", "en az", "yeterli geçmiş"),
    "veri_yok": ("veri yok", "boş", "empty", "not found", "bulunamadı"),
}


def classify_error(message: str) -> str:
    lowered = str(message).casefold()
    for kind, needles in ERROR_KINDS.items():
        if any(needle.casefold() in lowered for needle in needles):
            return kind
    return "ariza"


@dataclass
class ScreenResult:
    ticker: str
    close: float
    turnover: float
    bb_rank: float
    rvol: float
    atr_pct: float
    rsi: float
    screens: list[str] = field(default_factory=list)
    setup: str = ""
    setup_bias: str = ""
    relative_strength: str = ""
    excess_return_20: float = math.nan
    score: float = 0.0
    notes: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "close": self.close,
            "turnover": self.turnover,
            "bb_width_percentile": self.bb_rank,
            "rvol": self.rvol,
            "atr_pct": self.atr_pct,
            "rsi": self.rsi,
            "screens": self.screens,
            "setup": self.setup,
            "setup_bias": self.setup_bias,
            "relative_strength": self.relative_strength,
            "excess_return_20": self.excess_return_20,
            "score": self.score,
            "notes": self.notes,
            **self.detail,
        }


def excess_return(data: pd.DataFrame, benchmark: pd.Series | None, bars: int = 20) -> float:
    """Sembolün benchmarka göre son N bardaki getiri farkını puan olarak verir."""
    if benchmark is None or len(data) <= bars or len(benchmark) <= bars:
        return math.nan
    aligned = benchmark.reindex(data.index).ffill()
    if aligned.isna().iloc[-1] or aligned.isna().iloc[-bars - 1]:
        return math.nan
    stock = _number(data["Close"].iloc[-1]) / _number(data["Close"].iloc[-bars - 1]) - 1
    index = _number(aligned.iloc[-1]) / _number(aligned.iloc[-bars - 1]) - 1
    return (stock - index) * 100 if math.isfinite(stock) and math.isfinite(index) else math.nan


def relative_strength_label(excess: float) -> str:
    if not math.isfinite(excess):
        return "Benchmark verisi yok"
    if excess >= 3:
        return "Endeksten belirgin güçlü"
    if excess >= 0.5:
        return "Endeksten güçlü"
    if excess <= -3:
        return "Endeksten belirgin zayıf"
    if excess <= -0.5:
        return "Endeksten zayıf"
    return "Endeksle paralel"


# BIST'te günlük fiyat limiti ±%10'dur; tek barda bunu belirgin biçimde aşan
# hareket piyasa hareketi olamaz. Bölünme, sermaye artırımı veya veri hatasıdır.
# Düzeltilmemiş seri tüm göstergeleri bozar (RSI 18, CCI -589, "güçlü katılım").
PRICE_LIMIT_BY_MARKET = {"BIST": 0.10}
LIMIT_TOLERANCE = 1.25
# Bir barın kapsadığı işlem günü sayısı. Günlük limit birikimli olduğu için
# haftalık barda beş, aylıkta yirmi iki günlük hareket tek barda toplanır;
# günlük eşiği doğrudan uygulamak neredeyse her sembolü şüpheli gösterir.
TRADING_DAYS_PER_BAR = {"5m": 1, "15m": 1, "30m": 1, "1h": 1, "2h": 1, "4h": 1, "1d": 1, "1wk": 5, "1mo": 22}
# Aylık barda teorik sınır %700'ü aşar; tespit anlamını yitirdiğinden kapatılır.
MAX_USABLE_THRESHOLD = 1.0


def corporate_action_suspect(data: pd.DataFrame, market: str = "BIST", lookback: int = 60, interval: str = "1d") -> dict[str, Any]:
    """Fiyat limitini aşan bar var mı? Varsa seri düzeltilmemiş demektir.

    Eşik, barın kapsadığı işlem günü sayısına göre birikimli hesaplanır.
    """
    limit = PRICE_LIMIT_BY_MARKET.get(market.upper())
    if not limit or len(data) < 3:
        return {"suspect": False}
    days = TRADING_DAYS_PER_BAR.get(interval, 1)
    limit = (1 + limit) ** days - 1
    if limit > MAX_USABLE_THRESHOLD:
        return {"suspect": False, "reason": f"{interval} aralığında birikimli limit anlamlı bir eşik vermiyor; kontrol uygulanmadı."}
    closes = data["Close"].tail(lookback + 1)
    returns = closes.pct_change().dropna()
    threshold = limit * LIMIT_TOLERANCE
    breaches = returns[returns.abs() > threshold]
    if breaches.empty:
        return {"suspect": False}
    worst = breaches.abs().idxmax()
    change = float(breaches.loc[worst])
    age = int((pd.DatetimeIndex(closes.index) > worst).sum())
    return {
        "suspect": True,
        "date": pd.Timestamp(worst).date().isoformat(),
        "change_pct": round(change * 100, 2),
        "bars_ago": age,
        "reason": f"{pd.Timestamp(worst).date().isoformat()} tarihinde %{change * 100:.1f} hareket; "
        f"{interval} aralığında birikimli limit ±%{limit * 100:.0f} olduğundan bölünme/sermaye artırımı veya veri hatası olmalı.",
    }


def forming_bar_fraction(data: pd.DataFrame, interval: str, now: pd.Timestamp | None = None) -> float:
    """Son barın ne kadarının tamamlandığını verir (0-1).

    Gün içi taramada mevcut bar henüz kapanmamıştır; yarım barın hacmini tam bar
    ortalamasıyla kıyaslamak RVOL'ü sistematik olarak düşük gösterir. Saat başı
    çalışan taramalarda hacim koşulları bu yüzden hiç tetiklenmez.
    """
    from src.intervals import resolve

    spec = resolve(interval)
    stamps = pd.DatetimeIndex(data.index)
    last = stamps[-1]
    current = now or (pd.Timestamp.now(tz=last.tz) if last.tz else pd.Timestamp.now())
    if spec.key == "1d":
        # Günlük bar da seans ortasında yarımdır; seans uzunluğu üzerinden ölçülür.
        session_minutes = 480.0
        session_start = last.normalize() + pd.Timedelta(hours=10)
        if current.date() != last.date():
            return 1.0
        elapsed = (current - session_start).total_seconds() / 60
        if elapsed <= 0 or elapsed >= session_minutes:
            return 1.0
        return max(elapsed / session_minutes, 0.25)
    if spec.key in {"1wk", "1mo"}:
        # Devam eden hafta/ay barının hacmi de eksiktir; geçen süreye oranlanır.
        period_end = last + (pd.Timedelta(days=7) if spec.key == "1wk" else pd.offsets.MonthBegin(1))
        total = (period_end - last).total_seconds() / 60
        elapsed = (current - last).total_seconds() / 60
        if elapsed <= 0 or elapsed >= total:
            return 1.0
        return max(elapsed / total, 0.25)
    if not spec.intraday:
        return 1.0
    elapsed = (current - last).total_seconds() / 60
    if elapsed <= 0 or elapsed >= spec.minutes:
        return 1.0
    # Çok kısa süre geçtiyse aşırı büyütme yapmamak için taban konur.
    return max(elapsed / spec.minutes, 0.25)


def bar_freshness(data: pd.DataFrame, interval: str, now: pd.Timestamp | None = None) -> dict[str, Any]:
    """Son barın ne kadar eski olduğunu ölçer.

    Seans dışında çalışan taramada son bar gece barıdır; RVOL neredeyse sıfır
    çıkar ve hacme dayalı koşullar anlamsızlaşır. Bu durum raporlanmalıdır.
    """
    from src.intervals import resolve

    spec = resolve(interval)
    stamps = pd.DatetimeIndex(data.index)
    last = stamps[-1]
    current = now or pd.Timestamp.now(tz=last.tz) if last.tz else (now or pd.Timestamp.now())
    age_minutes = (current - last).total_seconds() / 60
    # Bir barlık gecikme normaldir; iki katından fazlası bayat sayılır.
    stale = age_minutes > spec.minutes * 2.5
    return {"last_bar": last.isoformat(), "age_minutes": round(age_minutes, 1), "stale": bool(stale)}


def basic_metrics(data: pd.DataFrame) -> dict[str, float]:
    """İlk aşama için gereken ucuz ölçütler."""
    row = data.iloc[-1]
    close = _number(row["Close"])
    volume = _number(row["Volume"])
    baseline = data["Volume"].shift(1).rolling(20, min_periods=5).mean().iloc[-1]
    turnover = _number((data["Close"] * data["Volume"]).tail(20).mean())
    # Pahalı aşamaya girecek sembolleri daraltmak için ucuz fiyat davranışı
    # göstergeleri. Tam kurulum tanıma yerine yalnızca ön eleme amaçlıdır.
    prior_low = _number(data["Low"].iloc[-21:-1].min())
    prior_high = _number(data["High"].iloc[-21:-1].max())
    pierced_down = _number(data["Low"].iloc[-1]) < prior_low <= close
    pierced_up = _number(data["High"].iloc[-1]) > prior_high >= close
    stack_up = all(close > _number(row.get(f"EMA_{period}", math.nan)) for period in (21, 55) if f"EMA_{period}" in data)
    stack_down = all(close < _number(row.get(f"EMA_{period}", math.nan)) for period in (21, 55) if f"EMA_{period}" in data)
    return {
        "rvol_raw": volume / _number(baseline) if _number(baseline) > 0 else math.nan,
        "pierced_down": bool(pierced_down),
        "pierced_up": bool(pierced_up),
        "stacked": bool(stack_up or stack_down),
        "close": close,
        "volume": volume,
        "turnover": turnover,
        "rvol": volume / _number(baseline) if _number(baseline) > 0 else math.nan,
        "bb_rank": _number(row.get("BB_WIDTH_RANK")),
        "atr_pct": _number(row.get("ATR_PCT")),
        "rsi": _number(row.get("RSI")),
        "adx": _number(row.get("ADX")),
        "macd_hist": _number(row.get("MACD_HIST")),
    }


# Her tarama: (ad, açıklama, ucuz ön koşul, kurulum sonrası koşul)
SCREENS: dict[str, dict[str, Any]] = {
    "sikisma_hacim": {
        "label": "Sıkışma + hacim",
        "description": "Dar Bollinger bandı üzerine ortalama üstü katılım geldi.",
        "cheap": lambda m, o: m["bb_rank"] <= o["bb_rank_max"] and m["rvol"] >= o["rvol_min"],
        "deep": None,
    },
    "hacim_patlamasi": {
        "label": "Hacim patlaması",
        "description": "Hacim son 20 barın ortalamasının belirgin biçimde üzerinde.",
        "cheap": lambda m, o: m["rvol"] >= o["rvol_spike"],
        "deep": None,
    },
    "asiri_bolge": {
        "label": "Uç RSI bölgesi",
        "description": "RSI uç bölgede; tükenme veya devam ayrımı için izlenmeli.",
        "cheap": lambda m, o: (m["rsi"] <= 25 or m["rsi"] >= 75) and m["rvol"] >= 1.0,
        "deep": None,
    },
    "basarisiz_kirilim": {
        "label": "Başarısız kırılım",
        "description": "Seviye aşağı/yukarı denendi ama kapanışla teyit edilmedi.",
        "cheap": lambda m, o: m["pierced_down"] or m["pierced_up"],
        "deep": lambda setup: "reddedilme" in str(setup.get("name", "")).casefold(),
    },
    "karar_bolgesi": {
        "label": "Karar bölgesi",
        "description": "Fiyat daralan aralıkta dengede; kırılım yönü henüz belirsiz.",
        "cheap": lambda m, o: m["bb_rank"] <= o["bb_rank_max"] and m["adx"] < 20,
        "deep": lambda setup: "sıkışma" in str(setup.get("name", "")).casefold(),
    },
    "trend_devami": {
        "label": "Trend devamı",
        "description": "Yapı, dizilim ve yönlülük aynı yönde ve harekete katılım var.",
        "cheap": lambda m, o: m["adx"] >= 25 and m["stacked"] and m["rvol"] >= 1.0,
        "deep": lambda setup: str(setup.get("name", "")) == "Trend devamı",
    },
    "tukenme": {
        "label": "Tükenme denemesi",
        "description": "Uyumsuzluk, teknik yoğunlaşma ve momentum aşırılığı bir arada.",
        "cheap": lambda m, o: (m["rsi"] <= 30 or m["rsi"] >= 70) and (m["pierced_down"] or m["pierced_up"]),
        "deep": lambda setup: str(setup.get("name", "")) == "Tükenme denemesi",
    },
}

DEEP_SCREENS = {name for name, screen in SCREENS.items() if screen["deep"]}

# Sıralama ağırlıkları: koşullu kurulum tanıyan taramalar, tek göstergeye dayalı
# olanlardan daha bilgilendiricidir.
SCREEN_WEIGHTS = {
    "basarisiz_kirilim": 3.0,
    "tukenme": 3.0,
    "sikisma_hacim": 3.0,
    "karar_bolgesi": 2.0,
    "trend_devami": 2.0,
    "hacim_patlamasi": 2.0,
    "asiri_bolge": 1.0,
}


def default_options() -> dict[str, float]:
    return {
        "bb_rank_max": 20.0,
        "rvol_min": 1.5,
        "rvol_spike": 3.0,
        "min_turnover": 20_000_000.0,
        "min_price": 1.0,
    }


def passes_liquidity(metrics: dict[str, float], options: dict[str, float]) -> bool:
    """İşlem görmeyen hisseler taramayı kirletmesin diye likidite eşiği."""
    return (
        math.isfinite(metrics["turnover"])
        and metrics["turnover"] >= options["min_turnover"]
        and _number(metrics["close"]) >= options["min_price"]
    )


def deep_context(data: pd.DataFrame) -> dict[str, Any]:
    """Kurulum tanıma için gereken pahalı bağlamı üretir."""
    structure = market_structure(data)
    profile = profile_context(data)
    divergences = detect_divergences(data)
    semantic = build_semantic_features(data, MA_PERIODS, {}, profile, {}, structure, divergences)
    row = data.iloc[-1]
    regime = "Trend / yönlü piyasa" if _number(row.get("ADX")) >= 25 else "Dengeli / sıkışan piyasa" if _number(row.get("ADX")) < 18 else "Geçiş / karma piyasa"
    context = {"regime": {"state": regime, "adx": _number(row.get("ADX"))}, "structure": structure, "profile": profile}
    result = build_setup_context(data, context, semantic)
    # Çözülme eşikleri sade özet satırında kullanılır; yapı seviyeleri taşınır.
    result["levels"] = {"swing_high": _number(structure.get("high")), "swing_low": _number(structure.get("low"))}
    return result


def screen_symbol_detailed(
    ticker: str,
    prices: pd.DataFrame,
    options: dict[str, float],
    enabled: Iterable[str],
    interval: str = "1d",
    benchmark: pd.Series | None = None,
) -> tuple[ScreenResult | None, str]:
    """Tek sembolü tarar ve eşleşme yoksa nedenini de döndürür.

    Neden bilgisi olmadan 'likidite elemesi' ile 'koşul karşılanmadı' aynı
    sayaçta toplanır ve rapor yanıltıcı olur.
    """
    enabled = list(enabled)
    data = calculate_indicators(prices, interval)
    suspect = corporate_action_suspect(prices, interval=interval)
    if suspect["suspect"]:
        return None, "corporate_action"
    metrics = basic_metrics(data)
    fraction = forming_bar_fraction(data, interval)
    if fraction < 1.0 and math.isfinite(metrics["rvol"]):
        # Oluşmakta olan bar, tamamlanan kısmına göre ölçeklenir.
        metrics["rvol"] = metrics["rvol"] / fraction
        metrics["bar_fraction"] = fraction
    if not passes_liquidity(metrics, options):
        return None, "illiquid"
    candidates = [name for name in enabled if SCREENS[name]["cheap"](metrics, options)]
    if not candidates:
        return None, "no_match"
    result = ScreenResult(
        ticker=ticker,
        close=metrics["close"],
        turnover=metrics["turnover"],
        bb_rank=metrics["bb_rank"],
        rvol=metrics["rvol"],
        atr_pct=metrics["atr_pct"],
        rsi=metrics["rsi"],
    )
    if metrics.get("bar_fraction"):
        fraction_pct = float(metrics["bar_fraction"]) * 100
        result.detail["bar_fraction"] = round(float(metrics["bar_fraction"]), 2)
        result.detail["rvol_observed"] = _number(metrics.get("rvol_raw"))
        result.notes.append(
            f"Mevcut bar %{fraction_pct:.0f} tamamlandı; gösterilen RVOL gün sonu projeksiyonudur "
            f"(şu ana kadar gerçekleşen: {_number(metrics.get('rvol_raw')):.2f}x)"
        )
    shallow = [name for name in candidates if name not in DEEP_SCREENS]
    matched = list(shallow)
    # Ucuz filtreyi geçen her sembolde derin analiz çalışır: eşleşen sembol sayısı
    # zaten azdır (yüzlerce değil onlarca) ve böylece her sonuç kurulum adı taşır.
    if candidates:
        setup_context = deep_context(data)
        setup = setup_context["setup"]
        result.setup = str(setup.get("name", ""))
        result.setup_bias = str(setup.get("bias", ""))
        result.detail["duration"] = setup_context["duration"]["summary"]
        result.detail["levels"] = setup_context.get("levels", {})
        # Ucuz ön koşul yalnızca derin analizi çalıştırmaya değer mi kararı içindir.
        # Analiz bir kez çalıştıktan sonra tüm derin koşullar değerlendirilir; aksi
        # halde kurulum "başarısız kırılım" derken tarama bunu kredilendirmez.
        matched.extend(name for name in enabled if name in DEEP_SCREENS and SCREENS[name]["deep"](setup))
        matched = list(dict.fromkeys(matched))
    if not matched:
        return None, "no_match"
    result.screens = matched
    result.excess_return_20 = excess_return(data, benchmark)
    result.relative_strength = relative_strength_label(result.excess_return_20)
    result.score = sum(SCREEN_WEIGHTS.get(name, 1.0) for name in matched)
    # Geniş bant üzerine gelen hacim patlaması, hareketin başı değil sonu olabilir.
    if "hacim_patlamasi" in matched and _number(metrics["bb_rank"], 0) >= 80:
        result.notes.append("Bantlar zaten geniş; hareketin geç aşaması olabilir")
    if result.setup_bias == "iki yönlü":
        result.notes.append("Kurulum koşullu; yön kapanışla netleşir")
    return result, "matched"


def screen_symbol(
    ticker: str,
    prices: pd.DataFrame,
    options: dict[str, float],
    enabled: Iterable[str],
    interval: str = "1d",
    benchmark: pd.Series | None = None,
) -> ScreenResult | None:
    """Geriye dönük uyumluluk: yalnızca eşleşmeyi döndürür."""
    return screen_symbol_detailed(ticker, prices, options, enabled, interval, benchmark)[0]


def rank_key(result: ScreenResult) -> tuple:
    """Eşleşmeleri ağırlıklı puana göre sıralar.

    Farklı türden taramaları ham RVOL ile kıyaslamak yanıltıcıdır; önce tarama
    ağırlıkları toplamı, sonra endeksten ayrışma büyüklüğü, en son likidite.
    """
    excess = abs(_number(result.excess_return_20, 0.0))
    return (-_number(result.score, 0.0), -excess, -_number(result.turnover, 0.0))


def chunked(items: list[str], size: int = BATCH_SIZE) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def run_screen(
    symbols: list[str],
    fetch: Callable[[list[str]], dict[str, pd.DataFrame]],
    options: dict[str, float] | None = None,
    enabled: Iterable[str] | None = None,
    interval: str = "1d",
    batch_size: int = BATCH_SIZE,
    benchmark: pd.Series | None = None,
    keep_frames: bool = False,
) -> dict[str, Any]:
    """Sembol listesini tarar ve her durumda özet döndürür."""
    options = {**default_options(), **(options or {})}
    enabled = list(enabled or SCREENS.keys())
    unknown = [name for name in enabled if name not in SCREENS]
    if unknown:
        raise ValueError(f"Bilinmeyen tarama: {', '.join(unknown)}")

    matches: list[ScreenResult] = []
    kept_frames: dict[str, pd.DataFrame] = {}
    errors: dict[str, str] = {}
    illiquid = 0
    no_match = 0
    corporate_actions: list[str] = []
    processed = 0
    freshness: dict[str, Any] | None = None
    for batch in chunked(symbols, batch_size):
        try:
            frames = fetch(batch)
        except Exception as error:  # noqa: BLE001 -- parti hatası taramayı durdurmamalı
            for ticker in batch:
                errors[ticker] = f"parti indirme hatası: {type(error).__name__}"
            continue
        for ticker in batch:
            frame = frames.get(ticker)
            if frame is None or frame.empty:
                errors[ticker] = "veri yok"
                continue
            try:
                processed += 1
                if freshness is None:
                    # İlk geçerli sembolden bar tazeliği ölçülür; seans dışı
                    # taramada hacim koşulları anlamsızlaşır ve bu raporlanmalıdır.
                    freshness = bar_freshness(frame, interval)
                result, reason = screen_symbol_detailed(ticker, frame, options, enabled, interval, benchmark)
                if result is None:
                    if reason == "illiquid":
                        illiquid += 1
                    elif reason == "corporate_action":
                        corporate_actions.append(ticker)
                    else:
                        no_match += 1
                    continue
                matches.append(result)
                if keep_frames:
                    # Eşleşen sembolün verisi rapor üretiminde yeniden kullanılır;
                    # aksi halde her rapor için ikinci bir indirme isteği gider.
                    kept_frames[ticker] = frame
            except Exception as error:  # noqa: BLE001 -- tek sembol tüm taramayı bozmasın
                errors[ticker] = f"{type(error).__name__}: {error}"[:160]
    matches.sort(key=rank_key)
    error_kinds: dict[str, list[str]] = {}
    for ticker, message in errors.items():
        error_kinds.setdefault(classify_error(message), []).append(ticker)
    return {
        "requested": len(symbols),
        "processed": processed,
        "matched": len(matches),
        "freshness": freshness or {},
        "corporate_actions": sorted(corporate_actions),
        "illiquid": illiquid,
        "no_match": no_match,
        "filtered_out": illiquid + no_match,
        "errors": errors,
        "error_kinds": {kind: sorted(tickers) for kind, tickers in error_kinds.items()},
        "options": options,
        "screens": enabled,
        "results": [item.as_dict() for item in matches],
        "frames": kept_frames,
    }

def merge_interval_results(payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Farklı zaman dilimlerinin sonuçlarını tek listede birleştirir.

    Bir sembolün hem saatlik hem günlükte aynı kurulumu vermesi, tek zaman
    dilimindeki eşleşmeden daha güçlü bir kanıttır; birleşik liste bunu görünür
    kılar ve çok zaman dilimli eşleşmeleri öne çıkarır.
    """
    combined: dict[str, dict[str, Any]] = {}
    for interval, payload in payloads.items():
        for item in payload.get("results", []):
            ticker = item["ticker"]
            entry = combined.setdefault(ticker, {**item, "intervals": {}, "screens": []})
            entry["intervals"][interval] = {
                "screens": item.get("screens", []),
                "setup": item.get("setup", ""),
                "rvol": item.get("rvol"),
                "bb_width_percentile": item.get("bb_width_percentile"),
            }
            entry["screens"] = list(dict.fromkeys(entry["screens"] + item.get("screens", [])))
            # Görünen değerler en kısa zaman diliminden alınır; en güncel odur.
            if interval == min(payloads, key=lambda key: INTERVAL_ORDER.get(key, 99)):
                entry.update({key: item[key] for key in ("close", "rvol", "bb_width_percentile", "setup", "setup_bias", "notes")})
            entry["excess_return_20"] = item.get("excess_return_20", entry.get("excess_return_20"))
    results = []
    for ticker, entry in combined.items():
        matched_intervals = list(entry["intervals"])
        entry["matched_intervals"] = matched_intervals
        entry["multi_timeframe"] = len(matched_intervals) > 1
        base = sum(SCREEN_WEIGHTS.get(name, 1.0) for name in entry["screens"])
        # Aynı kurulumun birden fazla zaman diliminde görülmesi puanı yükseltir.
        setups = {info.get("setup", "") for info in entry["intervals"].values() if info.get("setup")}
        agreement = 1.6 if len(matched_intervals) > 1 and len(setups) == 1 else 1.3 if len(matched_intervals) > 1 else 1.0
        entry["score"] = round(base * agreement, 2)
        entry["ticker"] = ticker
        results.append(entry)
    results.sort(key=lambda item: (-item["score"], -abs(_number(item.get("excess_return_20"), 0.0))))
    totals = {
        "requested": max((payload.get("requested", 0) for payload in payloads.values()), default=0),
        "processed": max((payload.get("processed", 0) for payload in payloads.values()), default=0),
        "illiquid": max((payload.get("illiquid", 0) for payload in payloads.values()), default=0),
        "no_match": max((payload.get("no_match", 0) for payload in payloads.values()), default=0),
    }
    errors: dict[str, str] = {}
    corporate: list[str] = []
    error_kinds: dict[str, list[str]] = {}
    for payload in payloads.values():
        errors.update(payload.get("errors", {}))
        corporate.extend(payload.get("corporate_actions", []))
        for kind, tickers in payload.get("error_kinds", {}).items():
            error_kinds.setdefault(kind, [])
            error_kinds[kind] = sorted(set(error_kinds[kind]) | set(tickers))
    freshness = next((payload.get("freshness", {}) for payload in payloads.values() if payload.get("freshness")), {})
    return {
        **totals,
        "matched": len(results),
        "filtered_out": totals["illiquid"] + totals["no_match"],
        "results": results,
        "errors": errors,
        "error_kinds": error_kinds,
        "corporate_actions": sorted(set(corporate)),
        "freshness": freshness,
        "intervals": list(payloads),
        "frames": {},
    }
