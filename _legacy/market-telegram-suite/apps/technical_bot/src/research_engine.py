"""Integrated company research engine for the technical Telegram bot.

The engine answers six separate questions instead of hiding everything behind a
single signal: company quality, balance-sheet trend, earnings quality, relative
valuation, technical structure/levels and risk. Missing data reduces coverage;
it is never converted into a negative score or fabricated value.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.fundamental_analysis import FundamentalReport, build_fundamental_report
from src.fundamental_quality import apply_coverage_policy


@dataclass(frozen=True)
class ResearchDimension:
    name: str
    score: float | None
    coverage: float
    label: str
    summary: str


@dataclass(frozen=True)
class LevelZone:
    side: str
    low: float
    high: float
    midpoint: float
    score: float
    status: str
    distance_atr: float
    touches: int
    age_bars: int | None
    sources: tuple[str, ...]


@dataclass(frozen=True)
class RiskItem:
    name: str
    score: float
    evidence: str


@dataclass(frozen=True)
class ResearchReport:
    symbol: str
    company_name: str
    price: float | None
    sector: str
    profile: str
    research_score: float | None
    coverage: float
    dimensions: tuple[ResearchDimension, ...]
    main_risk: RiskItem | None
    risks: tuple[RiskItem, ...]
    supports: tuple[LevelZone, ...]
    resistances: tuple[LevelZone, ...]
    technical: dict[str, Any]
    financial: dict[str, Any]
    valuation: dict[str, Any]
    fundamental: FundamentalReport
    note: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["fundamental"] = self.fundamental.to_dict()
        return payload


STATEMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("hasilat", "satis gelirleri", "net satislar", "revenue", "sales revenue"),
    "gross_profit": ("brut kar zarar", "brut kar", "gross profit loss", "gross profit"),
    "operating_profit": (
        "esas faaliyet kari zarari",
        "faaliyet kari zarari",
        "operating profit loss",
        "operating profit",
    ),
    "ebitda": ("favok", "ebitda", "earnings before interest taxes depreciation amortization"),
    "net_income": (
        "ana ortaklik paylari",
        "net donem kari",
        "donem kari zarari",
        "net income",
        "profit loss",
    ),
    "cfo": (
        "isletme faaliyetlerinden nakit akislari",
        "isletme faaliyetlerinden elde edilen nakit akislari",
        "net cash flows from operating activities",
        "cash flows from operating activities",
    ),
    "capex": (
        "maddi ve maddi olmayan duran varliklarin alimindan kaynaklanan nakit cikislari",
        "maddi duran varlik alimlari",
        "purchase of property plant and equipment",
        "capital expenditures",
    ),
    "cash": ("nakit ve nakit benzerleri", "cash and cash equivalents"),
    "assets": ("toplam varliklar", "varliklar toplam", "total assets"),
    "current_assets": ("donen varliklar", "current assets"),
    "equity": ("ozkaynaklar", "toplam ozkaynaklar", "total equity"),
    "current_liabilities": (
        "kisa vadeli yukumlulukler",
        "kisa vadeli borclar",
        "current liabilities",
    ),
    "inventory": ("stoklar", "inventories"),
    "receivables": ("ticari alacaklar", "trade receivables"),
    "payables": ("ticari borclar", "trade payables"),
    "short_debt": ("kisa vadeli borclanmalar", "short term borrowings", "short-term borrowings"),
    "current_long_debt": (
        "uzun vadeli borclanmalarin kisa vadeli kisimlari",
        "current portion of long term borrowings",
        "current portion of long-term borrowings",
    ),
    "long_debt": ("uzun vadeli borclanmalar", "long term borrowings", "long-term borrowings"),
    "finance_expense": ("finansman giderleri", "finance expenses", "financial expenses"),
}

CRITERIA = {
    "market_cap": "8",
    "pe": "28",
    "ev_ebitda": "29",
    "pb": "30",
    "ev_sales": "31",
    "dividend_yield": "33",
    "roe": "422",
}

BOUNDS = {
    "market_cap": (0, 5_000_000),
    "pe": (-1000, 10000),
    "ev_ebitda": (-100, 1000),
    "pb": (-100, 1000),
    "ev_sales": (-100, 1000),
    "dividend_yield": (0, 100),
    "roe": (-200, 500),
}

_PEER_CACHE: pd.DataFrame | None = None


def _norm(value: Any) -> str:
    text = str(value or "").strip().lower().replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_symbol(value: Any) -> str:
    text = str(value or "").upper().strip()
    for prefix in ("BIST:", "BIST-"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.replace(".IS", "").replace(".E", "").strip()


def _period_key(value: Any) -> tuple[int, int, int]:
    text = str(value)
    year_match = re.search(r"(19|20|21)\d{2}", text)
    year = int(year_match.group()) if year_match else 0
    quarter_match = re.search(r"[Qq]([1-4])", text)
    if quarter_match:
        return year, int(quarter_match.group(1)) * 3, 0
    nums = [int(item) for item in re.findall(r"\d+", text) if int(item) != year]
    month = next((item for item in nums if 1 <= item <= 12), 0)
    day = next((item for item in nums if 1 <= item <= 31 and item != month), 0)
    return year, month, day


def _statement_series(frame: pd.DataFrame | None, key: str) -> pd.Series | None:
    if frame is None or frame.empty:
        return None
    aliases = STATEMENT_ALIASES.get(key, ())
    labels = [(_norm(index), index) for index in frame.index]
    matches: list[Any] = []
    for alias in aliases:
        target = _norm(alias)
        exact = [index for label, index in labels if label == target]
        if exact:
            matches = exact
            break
    if not matches:
        candidates: list[tuple[int, Any]] = []
        for alias in aliases:
            target = _norm(alias)
            for label, index in labels:
                if target and target in label:
                    candidates.append((len(label), index))
        if candidates:
            matches = [sorted(candidates, key=lambda item: item[0])[0][1]]
    if not matches:
        return None

    selected = frame.loc[matches[0]]
    rows = selected if isinstance(selected, pd.DataFrame) else pd.DataFrame([selected])
    rows = rows.apply(pd.to_numeric, errors="coerce")
    row = max((item for _, item in rows.iterrows()), key=lambda item: int(item.notna().sum()), default=None)
    if row is None:
        return None
    ordered = sorted(row.index, key=_period_key)
    return row.reindex(ordered)


def _values(series: pd.Series | None) -> list[float | None]:
    if series is None:
        return []
    return [_finite(value) for value in pd.to_numeric(series, errors="coerce").tolist()]


def _latest(values: list[float | None], lag: int = 0) -> float | None:
    clean = [value for value in values if value is not None]
    if len(clean) <= lag:
        return None
    return clean[-1 - lag]


def _sum4(values: list[float | None], offset: int = 0) -> float | None:
    end = len(values) - offset
    start = end - 4
    if start < 0:
        return None
    chunk = values[start:end]
    return float(sum(value for value in chunk if value is not None)) if all(value is not None for value in chunk) else None


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or abs(previous) < 1e-9:
        return None
    return (current / abs(previous) - 1.0) * 100.0


def _ratio(num: float | None, den: float | None, scale: float = 1.0) -> float | None:
    if num is None or den is None or abs(den) < 1e-9:
        return None
    return num / den * scale


def _score_higher(value: float | None, bad: float, good: float) -> float | None:
    if value is None:
        return None
    return float(np.clip((value - bad) / (good - bad) * 100.0, 0.0, 100.0))


def _score_lower(value: float | None, good: float, bad: float) -> float | None:
    if value is None:
        return None
    return float(np.clip((bad - value) / (bad - good) * 100.0, 0.0, 100.0))


def _score_target(value: float | None, low: float, high: float, hard_low: float, hard_high: float) -> float | None:
    if value is None:
        return None
    if low <= value <= high:
        return 100.0
    if value < low:
        if value <= hard_low:
            return 0.0
        return float(np.clip((value - hard_low) / (low - hard_low) * 100.0, 0.0, 100.0))
    if value >= hard_high:
        return 0.0
    return float(np.clip((hard_high - value) / (hard_high - high) * 100.0, 0.0, 100.0))


def _weighted(values: list[tuple[float | None, float]]) -> tuple[float | None, float]:
    available = [(value, weight) for value, weight in values if value is not None]
    total_weight = sum(weight for _, weight in values)
    used_weight = sum(weight for _, weight in available)
    if not available or used_weight <= 0:
        return None, 0.0
    score = sum(float(value) * weight for value, weight in available) / used_weight
    coverage = used_weight / total_weight if total_weight else 0.0
    return round(score, 1), round(coverage, 2)


def _label(score: float | None, positive: str, neutral: str, negative: str) -> str:
    if score is None:
        return "VERİ YETERSİZ"
    if score >= 70:
        return positive
    if score >= 45:
        return neutral
    return negative


def _fetch_peer_snapshot() -> pd.DataFrame:
    global _PEER_CACHE
    if _PEER_CACHE is not None:
        return _PEER_CACHE.copy()

    import borsapy as bp

    raw = bp.Screener().run()
    if raw is None or raw.empty or "symbol" not in raw.columns:
        raise RuntimeError("BIST peer universe could not be loaded")
    frame = raw[[column for column in ("symbol", "name") if column in raw.columns]].copy()
    frame["symbol"] = frame["symbol"].map(_clean_symbol)
    frame = frame.drop_duplicates("symbol", keep="first")

    for name, criterion_id in CRITERIA.items():
        lo, hi = BOUNDS[name]
        metric = bp.Screener().add_filter(name, min=lo, max=hi, required=False).run()
        value_col = f"criteria_{criterion_id}"
        if metric is None or metric.empty or "symbol" not in metric.columns or value_col not in metric.columns:
            frame[name] = np.nan
            continue
        part = metric[["symbol", value_col]].rename(columns={value_col: name}).copy()
        part["symbol"] = part["symbol"].map(_clean_symbol)
        part[name] = pd.to_numeric(part[name], errors="coerce")
        frame = frame.merge(part.drop_duplicates("symbol"), on="symbol", how="left")

    try:
        from tradingview_screener import Query

        _, sector_raw = (
            Query().set_markets("turkey").select("name", "sector", "industry").limit(2000).get_scanner_data()
        )
        symbol_col = next((column for column in ("ticker", "name", "symbol") if column in sector_raw.columns), None)
        if symbol_col:
            sectors = sector_raw.copy()
            sectors["symbol"] = sectors[symbol_col].map(_clean_symbol)
            if "sector" not in sectors.columns:
                sectors["sector"] = None
            if "industry" not in sectors.columns:
                sectors["industry"] = None
            frame = frame.merge(
                sectors[["symbol", "sector", "industry"]].drop_duplicates("symbol"),
                on="symbol",
                how="left",
            )
    except Exception:  # noqa: BLE001 -- sector metadata is best effort
        frame["sector"] = "GENERIC"
        frame["industry"] = ""

    if "sector" not in frame.columns:
        frame["sector"] = "GENERIC"
    frame["sector"] = frame["sector"].fillna("GENERIC").replace("", "GENERIC")
    _PEER_CACHE = frame.copy()
    return frame


def _peer_valuation(symbol: str, profile: str) -> dict[str, Any]:
    try:
        frame = _fetch_peer_snapshot()
    except Exception as exc:  # noqa: BLE001
        return {"score": None, "coverage": 0.0, "scope": "unavailable", "error": str(exc), "metrics": {}}

    row = frame[frame["symbol"] == symbol]
    if row.empty:
        return {"score": None, "coverage": 0.0, "scope": "unavailable", "metrics": {}}
    sector = str(row.iloc[0].get("sector") or "GENERIC")
    peers = frame[frame["sector"] == sector] if sector != "GENERIC" else frame
    if len(peers) < 8:
        peers = frame
        scope = "BIST geneli"
    else:
        scope = f"{sector} sektörü"

    metrics = ["pe", "pb"] if profile == "BANK" else ["pb", "pe"] if profile == "GYO" else ["pe", "pb", "ev_ebitda", "ev_sales"]
    if "dividend_yield" in frame.columns:
        metrics.append("dividend_yield")

    scores: list[tuple[float | None, float]] = []
    detail: dict[str, Any] = {}
    for metric in metrics:
        series = pd.to_numeric(peers[metric], errors="coerce") if metric in peers.columns else pd.Series(dtype=float)
        if metric != "dividend_yield":
            series = series.where(series > 0)
        target = _finite(row.iloc[0].get(metric))
        if target is None or (metric != "dividend_yield" and target <= 0) or series.notna().sum() < 8:
            detail[metric] = {"value": target, "percentile": None}
            scores.append((None, 1.0))
            continue
        percentile = float((series.dropna() <= target).mean() * 100.0)
        score = percentile if metric == "dividend_yield" else 100.0 - percentile
        detail[metric] = {"value": target, "percentile": round(percentile, 1)}
        scores.append((score, 1.0))

    score, coverage = _weighted(scores)
    if profile == "GYO":
        note = "NAV/ekspertiz verisi yoksa GYO değerlemesi PD/DD ve mevcut çarpanlarla sınırlıdır."
    elif profile == "BANK":
        note = "Banka değerlemesinde F/K ve PD/DD önceliklidir; FD/FAVÖK kullanılmaz."
    else:
        note = "Çarpanlar aynı sektörle; sektör metadata yetersizse BIST geneliyle karşılaştırılır."
    return {"score": score, "coverage": coverage, "scope": scope, "sector": sector, "metrics": detail, "note": note}


def _fetch_statements(symbol: str, profile: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None]:
    import borsapy as bp

    group = "UFRS" if profile == "BANK" else "XI_29"
    stock = bp.Ticker(symbol)
    balance = stock.get_balance_sheet(quarterly=True, financial_group=group, last_n=8)
    income = stock.get_income_stmt(quarterly=True, financial_group=group, last_n=8)
    cashflow: pd.DataFrame | None = None
    if profile != "BANK":
        try:
            cashflow = stock.get_cashflow(quarterly=True, financial_group=group, last_n=8)
        except Exception:  # noqa: BLE001
            cashflow = None
    return balance, income, cashflow


def _financial_analysis(
    fundamental: FundamentalReport,
    balance: pd.DataFrame,
    income: pd.DataFrame,
    cashflow: pd.DataFrame | None,
) -> dict[str, Any]:
    metrics = dict(fundamental.metrics)
    if fundamental.profile == "BANK":
        balance_score, balance_cov = _weighted(
            [
                (_score_higher(metrics.get("assets_growth"), -5.0, 30.0), 1.0),
                (_score_higher(metrics.get("equity_growth"), -5.0, 30.0), 1.0),
                (_score_target(metrics.get("loans_deposits"), 0.75, 1.05, 0.35, 1.45), 1.0),
                (_score_higher(metrics.get("net_income_growth"), -20.0, 40.0), 1.0),
            ]
        )
        quality_score, quality_cov = _weighted(
            [
                (_score_higher(metrics.get("net_interest_growth"), -15.0, 35.0), 1.2),
                (_score_higher(metrics.get("roe"), 5.0, 35.0), 1.0),
                (_score_lower(metrics.get("operating_expense_growth"), -10.0, 40.0), 0.8),
                (_score_higher(metrics.get("net_income_growth"), -20.0, 40.0), 1.0),
            ]
        )
        return {
            "balance_score": balance_score,
            "balance_coverage": balance_cov,
            "balance_label": _label(balance_score, "İYİLEŞİYOR", "KARIŞIK", "ZAYIFLIYOR"),
            "earnings_quality_score": quality_score,
            "earnings_quality_coverage": quality_cov,
            "earnings_quality_label": _label(quality_score, "GÜÇLÜ", "ORTA", "ZAYIF"),
            "debt_direction": "BANKA İÇİN KLASİK NET BORÇ METRİĞİ UYGULANMAZ",
            "metrics": metrics,
            "note": "Banka riskinde resmi SYR, NPL ve karşılık oranı veri sağlayıcıda yoksa ayrıca gösterilmez.",
        }

    series = {key: _values(_statement_series(frame, key)) for key, frame in (
        ("revenue", income),
        ("gross_profit", income),
        ("operating_profit", income),
        ("ebitda", income),
        ("net_income", income),
        ("cfo", cashflow),
        ("capex", cashflow),
        ("cash", balance),
        ("assets", balance),
        ("current_assets", balance),
        ("current_liabilities", balance),
        ("equity", balance),
        ("inventory", balance),
        ("receivables", balance),
        ("short_debt", balance),
        ("current_long_debt", balance),
        ("long_debt", balance),
        ("finance_expense", income),
    )}

    revenue_ttm, revenue_prev = _sum4(series["revenue"]), _sum4(series["revenue"], 4)
    gross_ttm, gross_prev = _sum4(series["gross_profit"]), _sum4(series["gross_profit"], 4)
    op_ttm, op_prev = _sum4(series["operating_profit"]), _sum4(series["operating_profit"], 4)
    ebitda_ttm = _sum4(series["ebitda"])
    net_ttm, net_prev = _sum4(series["net_income"]), _sum4(series["net_income"], 4)
    cfo_ttm, cfo_prev = _sum4(series["cfo"]), _sum4(series["cfo"], 4)
    capex_ttm = _sum4(series["capex"])
    finance_ttm = _sum4(series["finance_expense"])

    revenue_growth = _growth(revenue_ttm, revenue_prev)
    op_growth = _growth(op_ttm, op_prev)
    net_growth = _growth(net_ttm, net_prev)
    cfo_growth = _growth(cfo_ttm, cfo_prev)
    gross_margin = _ratio(gross_ttm, revenue_ttm, 100.0)
    gross_margin_prev = _ratio(gross_prev, revenue_prev, 100.0)
    op_margin = _ratio(op_ttm, revenue_ttm, 100.0)
    op_margin_prev = _ratio(op_prev, revenue_prev, 100.0)
    net_margin = _ratio(net_ttm, revenue_ttm, 100.0)
    margin_delta = None if op_margin is None or op_margin_prev is None else op_margin - op_margin_prev

    current_assets = _latest(series["current_assets"])
    current_liabilities = _latest(series["current_liabilities"])
    current_ratio = _ratio(current_assets, current_liabilities)
    equity = _latest(series["equity"])
    assets = _latest(series["assets"])
    assets_prev = _latest(series["assets"], 4)
    cash = _latest(series["cash"])
    debt_now = sum(value or 0.0 for value in (
        _latest(series["short_debt"]),
        _latest(series["current_long_debt"]),
        _latest(series["long_debt"]),
    ))
    debt_prev_parts = (
        _latest(series["short_debt"], 4),
        _latest(series["current_long_debt"], 4),
        _latest(series["long_debt"], 4),
    )
    debt_prev = sum(value or 0.0 for value in debt_prev_parts) if any(value is not None for value in debt_prev_parts) else None
    cash_prev = _latest(series["cash"], 4)
    net_debt = debt_now - (cash or 0.0) if any(_latest(series[key]) is not None for key in ("short_debt", "current_long_debt", "long_debt")) else None
    net_debt_prev = None if debt_prev is None else debt_prev - (cash_prev or 0.0)
    net_debt_change = _growth(net_debt, net_debt_prev)
    net_debt_equity = _ratio(net_debt, equity)
    net_debt_ebitda = _ratio(net_debt, ebitda_ttm)
    interest_coverage = _ratio(op_ttm, abs(finance_ttm)) if finance_ttm not in (None, 0) else None

    cfo_net_income = _ratio(cfo_ttm, net_ttm)
    fcf = None if cfo_ttm is None else cfo_ttm - abs(capex_ttm or 0.0)
    fcf_margin = _ratio(fcf, revenue_ttm, 100.0)
    average_assets = None if assets is None or assets_prev is None else (assets + assets_prev) / 2.0
    accrual_ratio = _ratio(None if net_ttm is None or cfo_ttm is None else net_ttm - cfo_ttm, average_assets, 100.0)

    revenue_q_growth = _growth(_latest(series["revenue"]), _latest(series["revenue"], 4))
    receivables_growth = _growth(_latest(series["receivables"]), _latest(series["receivables"], 4))
    inventory_growth = _growth(_latest(series["inventory"]), _latest(series["inventory"], 4))
    receivable_gap = None if receivables_growth is None or revenue_q_growth is None else receivables_growth - revenue_q_growth
    inventory_gap = None if inventory_growth is None or revenue_q_growth is None else inventory_growth - revenue_q_growth

    balance_score, balance_cov = _weighted(
        [
            (_score_higher(revenue_growth, -10.0, 30.0), 1.0),
            (_score_higher(op_growth, -15.0, 35.0), 1.0),
            (_score_higher(net_growth, -20.0, 40.0), 1.2),
            (_score_higher(margin_delta, -5.0, 5.0), 1.0),
            (_score_lower(net_debt_change, -25.0, 50.0), 1.2),
            (_score_target(current_ratio, 1.2, 2.8, 0.6, 6.0), 0.8),
        ]
    )
    quality_score, quality_cov = _weighted(
        [
            (_score_target(cfo_net_income, 0.8, 1.8, -0.3, 4.0), 1.5),
            (_score_higher(fcf_margin, -10.0, 20.0), 1.1),
            (_score_lower(accrual_ratio, -5.0, 15.0), 1.0),
            (_score_lower(receivable_gap, -15.0, 40.0), 0.8),
            (_score_lower(inventory_gap, -15.0, 50.0), 0.8),
            (_score_higher(cfo_growth, -20.0, 40.0), 0.8),
        ]
    )

    if net_debt_change is None:
        debt_direction = "VERİ YETERSİZ"
    elif net_debt_change <= -10:
        debt_direction = "AZALIYOR"
    elif net_debt_change >= 10:
        debt_direction = "ARTIYOR"
    else:
        debt_direction = "YATAY / SINIRLI DEĞİŞİM"

    snapshot = {
        "revenue_growth": revenue_growth,
        "operating_growth": op_growth,
        "net_income_growth": net_growth,
        "gross_margin": gross_margin,
        "gross_margin_yoy_change_pp": None if gross_margin is None or gross_margin_prev is None else gross_margin - gross_margin_prev,
        "operating_margin": op_margin,
        "operating_margin_yoy_change_pp": margin_delta,
        "net_margin": net_margin,
        "current_ratio": current_ratio,
        "net_debt": net_debt,
        "net_debt_yoy_change": net_debt_change,
        "net_debt_equity": net_debt_equity,
        "net_debt_ebitda": net_debt_ebitda,
        "interest_coverage": interest_coverage,
        "cfo_net_income": cfo_net_income,
        "fcf_margin": fcf_margin,
        "accrual_ratio": accrual_ratio,
        "receivables_growth": receivables_growth,
        "inventory_growth": inventory_growth,
        "receivables_vs_sales_gap": receivable_gap,
        "inventory_vs_sales_gap": inventory_gap,
    }
    return {
        "balance_score": balance_score,
        "balance_coverage": balance_cov,
        "balance_label": _label(balance_score, "İYİLEŞİYOR", "KARIŞIK", "ZAYIFLIYOR"),
        "earnings_quality_score": quality_score,
        "earnings_quality_coverage": quality_cov,
        "earnings_quality_label": _label(quality_score, "GÜÇLÜ", "ORTA", "ZAYIF"),
        "debt_direction": debt_direction,
        "metrics": snapshot,
        "note": "Trendler son 8 çeyrekten; TTM ve yıllık karşılaştırmalarla hesaplanır.",
    }


def _prepare_prices(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise RuntimeError("Price history is empty")
    rename = {column: str(column).title() for column in frame.columns}
    data = frame.rename(columns=rename).copy()
    required = {"Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(data.columns):
        raise RuntimeError(f"Price history misses OHLCV columns: {sorted(required - set(data.columns))}")
    data = data[list(required)].sort_index().dropna(subset=["Open", "High", "Low", "Close"])
    close = data["Close"].astype(float)
    for period in (21, 55, 233):
        data[f"EMA_{period}"] = close.ewm(span=period, adjust=False, min_periods=period).mean()
    prev_close = close.shift(1)
    true_range = pd.concat(
        [(data["High"] - data["Low"]), (data["High"] - prev_close).abs(), (data["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    data["ATR"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    change = close.diff()
    gain = change.clip(lower=0.0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-change.clip(upper=0.0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0.0, np.nan)
    data["RSI"] = 100.0 - 100.0 / (1.0 + rs)
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    data["MACD"] = ema12 - ema26
    data["MACD_SIGNAL"] = data["MACD"].ewm(span=9, adjust=False, min_periods=9).mean()
    data["MACD_HIST"] = data["MACD"] - data["MACD_SIGNAL"]
    return data


def _pivots(data: pd.DataFrame, left: int = 3, right: int = 3) -> list[dict[str, Any]]:
    highs = data["High"].to_numpy(dtype=float)
    lows = data["Low"].to_numpy(dtype=float)
    result: list[dict[str, Any]] = []
    last_high: float | None = None
    last_low: float | None = None
    for index in range(left, len(data) - right):
        high_window = highs[index - left : index + right + 1]
        low_window = lows[index - left : index + right + 1]
        if highs[index] == np.max(high_window) and int(np.count_nonzero(high_window == highs[index])) == 1:
            label = "H" if last_high is None else "HH" if highs[index] > last_high else "LH"
            result.append({"index": index, "type": "high", "price": float(highs[index]), "label": label, "time": str(data.index[index])})
            last_high = float(highs[index])
        if lows[index] == np.min(low_window) and int(np.count_nonzero(low_window == lows[index])) == 1:
            label = "L" if last_low is None else "HL" if lows[index] > last_low else "LL"
            result.append({"index": index, "type": "low", "price": float(lows[index]), "label": label, "time": str(data.index[index])})
            last_low = float(lows[index])
    return sorted(result, key=lambda item: item["index"])


def _structure(data: pd.DataFrame, pivots: list[dict[str, Any]]) -> dict[str, Any]:
    highs = [item for item in pivots if item["type"] == "high"]
    lows = [item for item in pivots if item["type"] == "low"]
    high_label = highs[-1]["label"] if highs else "—"
    low_label = lows[-1]["label"] if lows else "—"
    state = f"{high_label} / {low_label}"
    close = float(data["Close"].iloc[-1])
    bos = "Yeni yapı kırılımı yok"
    if highs and close > float(highs[-1]["price"]):
        bos = "Swing High üzeri BOS"
    elif lows and close < float(lows[-1]["price"]):
        bos = "Swing Low altı BOS"
    return {
        "state": state,
        "bos": bos,
        "last_high": highs[-1] if highs else None,
        "last_low": lows[-1] if lows else None,
    }


def _volume_poc(data: pd.DataFrame, lookback: int = 100, bins: int = 40) -> float | None:
    window = data.tail(lookback)
    if window.empty:
        return None
    typical = (window["High"] + window["Low"] + window["Close"]) / 3.0
    low, high = float(window["Low"].min()), float(window["High"].max())
    if high <= low:
        return None
    edges = np.linspace(low, high, bins + 1)
    bucket = np.clip(np.digitize(typical, edges) - 1, 0, bins - 1)
    volumes = np.zeros(bins, dtype=float)
    for position, volume in zip(bucket, window["Volume"].fillna(0.0), strict=False):
        volumes[int(position)] += float(volume)
    if volumes.sum() <= 0:
        return None
    index = int(volumes.argmax())
    return float((edges[index] + edges[index + 1]) / 2.0)


def _level_zones(data: pd.DataFrame, pivots: list[dict[str, Any]]) -> tuple[tuple[LevelZone, ...], tuple[LevelZone, ...]]:
    price = float(data["Close"].iloc[-1])
    atr = _finite(data["ATR"].iloc[-1]) or price * 0.02
    candidates: list[dict[str, Any]] = []

    for item in pivots[-24:]:
        candidates.append({"value": float(item["price"]), "source": item["label"], "index": int(item["index"])})
    for period in (21, 55, 233):
        value = _finite(data[f"EMA_{period}"].iloc[-1])
        if value is not None:
            candidates.append({"value": value, "source": f"EMA{period}", "index": None})
    poc = _volume_poc(data)
    if poc is not None:
        candidates.append({"value": poc, "source": "POC", "index": None})

    if len(pivots) >= 2:
        a, b = pivots[-2], pivots[-1]
        if a["type"] != b["type"] and abs(float(b["price"]) - float(a["price"])) >= atr:
            lo, hi = sorted((float(a["price"]), float(b["price"])))
            for ratio, label in ((0.382, "Fib38.2"), (0.5, "Fib50"), (0.618, "Fib61.8"), (0.786, "Fib78.6")):
                value = hi - (hi - lo) * ratio if b["type"] == "high" else lo + (hi - lo) * ratio
                candidates.append({"value": value, "source": label, "index": None})

    threshold = max(atr * 0.35, price * 0.004)
    candidates.sort(key=lambda item: item["value"])
    clusters: list[list[dict[str, Any]]] = []
    for item in candidates:
        if not clusters or item["value"] - float(np.mean([x["value"] for x in clusters[-1]])) > threshold:
            clusters.append([item])
        else:
            clusters[-1].append(item)

    zones: list[LevelZone] = []
    tail = data.tail(180).reset_index(drop=True)
    for cluster in clusters:
        values = [float(item["value"]) for item in cluster]
        low, high = min(values), max(values)
        midpoint = float(np.mean(values))
        side = "destek" if midpoint < price else "direnç"
        distance_atr = abs(midpoint - price) / atr if atr > 0 else math.inf
        overlap = (tail["Low"] <= high + threshold * 0.2) & (tail["High"] >= low - threshold * 0.2)
        touch_positions = np.flatnonzero(overlap.to_numpy())
        separated: list[int] = []
        for position in touch_positions:
            if not separated or int(position) - separated[-1] >= 3:
                separated.append(int(position))
        touches = len(separated)
        age = None if not separated else int(len(tail) - 1 - separated[-1])
        reactions: list[float] = []
        for position in separated[-5:]:
            forward = tail.iloc[position + 1 : position + 6]
            if forward.empty:
                continue
            if side == "destek":
                reactions.append(max(float(forward["High"].max()) - midpoint, 0.0) / atr)
            else:
                reactions.append(max(midpoint - float(forward["Low"].min()), 0.0) / atr)
        reaction = max(reactions, default=0.0)

        close = tail["Close"].astype(float)
        cross_up = ((close.shift(1) < low) & (close > high)).fillna(False)
        cross_down = ((close.shift(1) > high) & (close < low)).fillna(False)
        if side == "destek" and cross_up.any():
            status = "KIRILMIŞ DİRENÇ → DESTEK"
        elif side == "direnç" and cross_down.any():
            status = "KIRILMIŞ DESTEK → DİRENÇ"
        else:
            status = "AKTİF DESTEK" if side == "destek" else "AKTİF DİRENÇ"
        if distance_atr > 6 or (age is not None and age > 100):
            status = "TARİHSEL / UZAK SEVİYE"

        sources = tuple(sorted({str(item["source"]) for item in cluster}))
        score = min(touches, 3) * 10.0 + min(len(sources), 3) * 12.0 + min(reaction, 2.0) * 7.5
        score += 20.0 if age is not None and age <= 20 else 10.0 if age is not None and age <= 60 else 0.0
        score -= 20.0 if distance_atr > 4 else 0.0
        score = float(np.clip(score, 0.0, 100.0))
        zones.append(
            LevelZone(
                side=side,
                low=round(low, 4),
                high=round(high, 4),
                midpoint=round(midpoint, 4),
                score=round(score, 1),
                status=status,
                distance_atr=round(distance_atr, 2),
                touches=touches,
                age_bars=age,
                sources=sources,
            )
        )

    actionable = [zone for zone in zones if zone.status != "TARİHSEL / UZAK SEVİYE"]
    supports = sorted((zone for zone in actionable if zone.side == "destek"), key=lambda zone: (-zone.score, zone.distance_atr))[:2]
    resistances = sorted((zone for zone in actionable if zone.side == "direnç"), key=lambda zone: (-zone.score, zone.distance_atr))[:2]
    return tuple(supports), tuple(resistances)


def _technical_analysis(symbol: str) -> tuple[dict[str, Any], tuple[LevelZone, ...], tuple[LevelZone, ...]]:
    import borsapy as bp

    stock = bp.Ticker(symbol)
    daily = _prepare_prices(stock.history(period="2y", interval="1d"))
    daily = daily.dropna(subset=["ATR"]).copy()
    if len(daily) < 80:
        raise RuntimeError("Insufficient daily history for technical research")
    pivots = _pivots(daily)
    structure = _structure(daily, pivots)
    supports, resistances = _level_zones(daily, pivots)

    row = daily.iloc[-1]
    price = float(row["Close"])
    ema21, ema55, ema233 = (_finite(row[f"EMA_{period}"]) for period in (21, 55, 233))
    ema_score = 50.0
    if ema21 is not None and ema55 is not None and ema233 is not None:
        ema_score = 90.0 if price > ema21 > ema55 > ema233 else 10.0 if price < ema21 < ema55 < ema233 else 50.0
    structure_score = 85.0 if structure["state"] == "HH / HL" else 15.0 if structure["state"] == "LH / LL" else 50.0
    rsi = _finite(row["RSI"])
    hist = _finite(row["MACD_HIST"])
    momentum_score, _ = _weighted(
        [
            (_score_target(rsi, 50.0, 68.0, 25.0, 85.0), 1.0),
            (_score_higher(hist, -abs(price) * 0.01, abs(price) * 0.01), 1.0),
        ]
    )

    weekly = _prepare_prices(
        daily[["Open", "High", "Low", "Close", "Volume"]]
        .resample("W-FRI")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna()
    )
    weekly_pivots = _pivots(weekly, left=2, right=2)
    weekly_structure = _structure(weekly, weekly_pivots) if weekly_pivots else {"state": "—", "bos": "—"}
    weekly_score = 80.0 if weekly_structure["state"] == "HH / HL" else 20.0 if weekly_structure["state"] == "LH / LL" else 50.0
    technical_score, technical_cov = _weighted(
        [(structure_score, 1.3), (ema_score, 1.1), (momentum_score, 1.0), (weekly_score, 1.0)]
    )
    atr = float(row["ATR"])
    atr_pct = atr / price * 100.0 if price else None
    turnover = (daily["Close"] * daily["Volume"]).tail(20)
    avg_turnover = _finite(turnover.mean())
    volume_mean = _finite(daily["Volume"].iloc[-21:-1].mean())
    rvol = _ratio(_finite(row["Volume"]), volume_mean)
    return (
        {
            "score": technical_score,
            "coverage": technical_cov,
            "label": _label(technical_score, "POZİTİF", "KARIŞIK", "ZAYIF"),
            "structure": structure,
            "weekly_structure": weekly_structure,
            "ema21": ema21,
            "ema55": ema55,
            "ema233": ema233,
            "rsi14": rsi,
            "macd_hist": hist,
            "atr": atr,
            "atr_pct": atr_pct,
            "rvol20": rvol,
            "average_turnover_20": avg_turnover,
            "pivots": pivots[-12:],
        },
        supports,
        resistances,
    )


def _risk_engine(
    profile: str,
    financial: dict[str, Any],
    valuation: dict[str, Any],
    technical: dict[str, Any],
    supports: tuple[LevelZone, ...],
) -> tuple[RiskItem | None, tuple[RiskItem, ...]]:
    fm = financial.get("metrics", {})
    risks: list[RiskItem] = []

    if profile == "BANK":
        capital_proxy = fm.get("equity_assets")
        loan_deposit = fm.get("loans_deposits")
        bank_score, _ = _weighted(
            [
                (_score_lower(capital_proxy, 14.0, 5.0), 1.0),
                (_score_lower(abs((loan_deposit or 0.9) - 0.9), 0.0, 0.5), 1.0),
            ]
        )
        bank_risk = 50.0 if bank_score is None else 100.0 - bank_score
        risks.append(
            RiskItem(
                "Banka bilanço riski",
                round(bank_risk, 1),
                "Resmi SYR/NPL yoksa özkaynak/aktif ve kredi/mevduat yalnız vekil göstergedir.",
            )
        )
    else:
        nde = fm.get("net_debt_equity")
        nd_ebitda = fm.get("net_debt_ebitda")
        current_ratio = fm.get("current_ratio")
        leverage_score, _ = _weighted(
            [
                (_score_lower(nde, 0.0, 2.0), 1.0),
                (_score_lower(nd_ebitda, 0.0, 4.0), 1.2),
                (_score_target(current_ratio, 1.2, 2.8, 0.5, 6.0), 0.8),
            ]
        )
        leverage_risk = 50.0 if leverage_score is None else 100.0 - leverage_score
        risks.append(
            RiskItem(
                "Finansal kaldıraç",
                round(leverage_risk, 1),
                f"Net borç yönü: {financial.get('debt_direction', '—')}; net borç/FAVÖK {nd_ebitda if nd_ebitda is not None else '—'}.",
            )
        )

    quality_score = financial.get("earnings_quality_score")
    risks.append(
        RiskItem(
            "Kâr kalitesi",
            round(50.0 if quality_score is None else 100.0 - float(quality_score), 1),
            f"CFO/net kâr {fm.get('cfo_net_income', '—')} · accrual %{fm.get('accrual_ratio', '—')}.",
        )
    )
    valuation_score = valuation.get("score")
    risks.append(
        RiskItem(
            "Değerleme hassasiyeti",
            round(50.0 if valuation_score is None else 100.0 - float(valuation_score), 1),
            f"Karşılaştırma kapsamı: {valuation.get('scope', '—')}.",
        )
    )
    technical_score = technical.get("score")
    atr_pct = _finite(technical.get("atr_pct"))
    support_penalty = 15.0 if not supports else min(float(supports[0].distance_atr) * 4.0, 20.0)
    technical_risk = 50.0 if technical_score is None else 100.0 - float(technical_score)
    technical_risk = min(100.0, technical_risk + support_penalty + (10.0 if atr_pct is not None and atr_pct > 5 else 0.0))
    risks.append(
        RiskItem(
            "Teknik yapı",
            round(technical_risk, 1),
            f"Yapı {technical.get('structure', {}).get('state', '—')} · ATR %{atr_pct:.1f}" if atr_pct is not None else "Teknik volatilite verisi yetersiz.",
        )
    )

    turnover = _finite(technical.get("average_turnover_20"))
    if turnover is None:
        liquidity_risk = 50.0
    elif turnover < 25_000_000:
        liquidity_risk = 85.0
    elif turnover < 100_000_000:
        liquidity_risk = 55.0
    else:
        liquidity_risk = 20.0
    risks.append(RiskItem("Likidite", liquidity_risk, f"20 günlük ortalama TL hacim {turnover:,.0f}." if turnover else "TL hacim hesaplanamadı."))

    ordered = tuple(sorted(risks, key=lambda item: item.score, reverse=True))
    return (ordered[0] if ordered else None), ordered


def build_research_report(symbol: str) -> ResearchReport:
    """Build the integrated technical + financial + valuation + risk report."""
    ticker = symbol.strip().upper().removesuffix(".IS")
    fundamental = apply_coverage_policy(build_fundamental_report(ticker))
    balance, income, cashflow = _fetch_statements(ticker, fundamental.profile)
    financial = _financial_analysis(fundamental, balance, income, cashflow)
    valuation = _peer_valuation(ticker, fundamental.profile)
    technical, supports, resistances = _technical_analysis(ticker)

    quality_score = None if fundamental.overall_score is None else fundamental.overall_score / 5.0 * 100.0
    dimensions = (
        ResearchDimension(
            "Şirket Kalitesi",
            None if quality_score is None else round(quality_score, 1),
            fundamental.coverage,
            _label(quality_score, "GÜÇLÜ", "ORTA", "ZAYIF"),
            "Sektör uyarlamalı kârlılık, büyüme, sermaye/bilanço ve nakit faktörleri.",
        ),
        ResearchDimension(
            "Bilanço Trendi",
            financial.get("balance_score"),
            financial.get("balance_coverage", 0.0),
            financial.get("balance_label", "VERİ YETERSİZ"),
            f"Son 8 çeyrek; borç yönü: {financial.get('debt_direction', '—')}.",
        ),
        ResearchDimension(
            "Kâr Kalitesi",
            financial.get("earnings_quality_score"),
            financial.get("earnings_quality_coverage", 0.0),
            financial.get("earnings_quality_label", "VERİ YETERSİZ"),
            "Nakit dönüşümü, FCF, accrual ve işletme sermayesi ayrışmaları birlikte okunur.",
        ),
        ResearchDimension(
            "Değerleme",
            valuation.get("score"),
            valuation.get("coverage", 0.0),
            _label(valuation.get("score"), "İSKONTOLU / GÜÇLÜ", "MAKUL", "PRİMLİ / ZAYIF"),
            f"{valuation.get('scope', 'Karşılaştırma yok')} göre göreli çarpan konumu.",
        ),
        ResearchDimension(
            "Teknik Yapı",
            technical.get("score"),
            technical.get("coverage", 0.0),
            technical.get("label", "VERİ YETERSİZ"),
            f"Günlük yapı {technical.get('structure', {}).get('state', '—')}; haftalık {technical.get('weekly_structure', {}).get('state', '—')}.",
        ),
    )

    research_score, coverage = _weighted([(dimension.score, 1.0) for dimension in dimensions])
    main_risk, risks = _risk_engine(fundamental.profile, financial, valuation, technical, supports)
    note = (
        "Araştırma skoru tavsiye değildir. Değerleme sektör-göreli; GYO NAV, banka SYR/NPL gibi sağlayıcıda olmayan "
        "kritik veriler uydurulmaz ve kapsam puanına yansır. Uzak/eski teknik seviyeler aksiyon seviyesi olarak gösterilmez."
    )
    return ResearchReport(
        symbol=ticker,
        company_name=fundamental.company_name,
        price=fundamental.price,
        sector=fundamental.sector,
        profile=fundamental.profile,
        research_score=research_score,
        coverage=coverage,
        dimensions=dimensions,
        main_risk=main_risk,
        risks=risks,
        supports=supports,
        resistances=resistances,
        technical=technical,
        financial=financial,
        valuation=valuation,
        fundamental=fundamental,
        note=note,
    )
