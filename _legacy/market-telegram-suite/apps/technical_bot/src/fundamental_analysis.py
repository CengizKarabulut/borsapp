"""Sector-aware fundamental analysis for Telegram cards.

The module intentionally separates data collection from scoring. It uses borsapy
for BIST market/fundamental data and returns a compact, serialisable report model.
Scores are descriptive 0-5 factor scores, not buy/sell recommendations.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

BANK_SYMBOLS = {
    "AKBNK",
    "ALBRK",
    "GARAN",
    "HALKB",
    "ICBCT",
    "ISCTR",
    "KLNMA",
    "QNBTR",
    "SKBNK",
    "TSKB",
    "VAKBN",
    "YKBNK",
}

STATEMENT_ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "sales revenue",
        "revenue",
        "net sales",
        "sales",
        "hasılat",
        "hasilat",
        "satış gelirleri",
        "satis gelirleri",
        "net satışlar",
        "net satislar",
    ),
    "gross_profit": ("gross profit", "brüt kar", "brut kar"),
    "operating_profit": (
        "operating profit",
        "operating income",
        "faaliyet karı",
        "faaliyet kari",
        "esas faaliyet karı",
        "esas faaliyet kari",
    ),
    "ebitda": (
        "ebitda",
        "earnings before interest taxes depreciation and amortization",
        "favök",
        "favok",
        "faiz amortisman vergi öncesi kar",
        "faiz amortisman vergi oncesi kar",
    ),
    "net_income": (
        "net income",
        "net profit",
        "net dönem karı",
        "net donem kari",
        "ana ortaklık payları",
        "ana ortaklik paylari",
        "dönem karı",
        "donem kari",
    ),
    "cfo": (
        "cash flows from operating activities",
        "operating cash flow",
        "işletme faaliyetlerinden nakit akışları",
        "isletme faaliyetlerinden nakit akislari",
    ),
    "capex": (
        "capital expenditures",
        "purchase of property plant equipment",
        "maddi ve maddi olmayan duran varlık alımları",
        "maddi ve maddi olmayan duran varlik alimlari",
    ),
    "cash": (
        "cash and cash equivalents",
        "nakit ve nakit benzerleri",
        "nakit ve nakit benzerleri toplamı",
        "nakit ve nakit benzerleri toplami",
    ),
    "assets": ("total assets", "toplam varlıklar", "toplam varliklar", "aktif toplamı", "aktif toplami"),
    "current_assets": ("current assets", "dönen varlıklar", "donen varliklar"),
    "equity": (
        "total equity",
        "equity",
        "özkaynaklar",
        "ozkaynaklar",
        "ana ortaklığa ait özkaynaklar",
        "ana ortakliga ait ozkaynaklar",
    ),
    "current_liabilities": (
        "current liabilities",
        "kısa vadeli yükümlülükler",
        "kisa vadeli yukumlulukler",
    ),
    "short_debt": (
        "short term borrowings",
        "short-term borrowings",
        "kısa vadeli borçlanmalar",
        "kisa vadeli borclanmalar",
    ),
    "long_debt": (
        "long term borrowings",
        "long-term borrowings",
        "uzun vadeli borçlanmalar",
        "uzun vadeli borclanmalar",
    ),
    "interest_income": ("interest income", "faiz gelirleri", "faiz gelirleri toplamı", "faiz gelirleri toplami"),
    "interest_expense": ("interest expense", "faiz giderleri", "faiz giderleri toplamı", "faiz giderleri toplami"),
    "net_interest_income": ("net interest income", "net faiz geliri", "net faiz gelirleri"),
    "operating_expense": (
        "operating expenses",
        "faaliyet giderleri",
        "operasyonel giderler",
    ),
    "loans": (
        "loans and receivables",
        "loans",
        "krediler",
        "nakdi krediler",
    ),
    "deposits": ("deposits", "mevduat", "mevduatlar"),
}


@dataclass(frozen=True)
class Factor:
    name: str
    score: float | None
    coverage: float
    detail: str


@dataclass(frozen=True)
class FundamentalReport:
    symbol: str
    company_name: str
    price: float | None
    sector: str
    profile: str
    overall_score: float | None
    coverage: float
    factors: tuple[Factor, ...]
    positives: tuple[str, ...]
    risks: tuple[str, ...]
    metrics: dict[str, float | None]
    note: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["factors"] = [asdict(item) for item in self.factors]
        return payload


def _norm(value: Any) -> str:
    text = str(value).strip().casefold()
    replacements = str.maketrans("çğıöşü", "cgiosu")
    text = text.translate(replacements)
    return re.sub(r"[^a-z0-9]+", "", text)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _pick(mapping: dict[str, Any], *names: str) -> float | None:
    for name in names:
        if name in mapping:
            value = _finite(mapping.get(name))
            if value is not None:
                return value
    normalised = {_norm(key): value for key, value in mapping.items()}
    for name in names:
        value = _finite(normalised.get(_norm(name)))
        if value is not None:
            return value
    return None


def _pick_text(mapping: dict[str, Any], *names: str) -> str:
    for name in names:
        value = mapping.get(name)
        if value not in (None, ""):
            return str(value).strip()
    normalised = {_norm(key): value for key, value in mapping.items()}
    for name in names:
        value = normalised.get(_norm(name))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _period_key(value: Any) -> tuple[int, int, int]:
    text = str(value)
    numbers = [int(item) for item in re.findall(r"\d+", text)]
    if not numbers:
        return (0, 0, 0)
    year = next((item for item in numbers if 1900 <= item <= 2200), 0)
    others = [item for item in numbers if item != year]
    month = next((item for item in others if 1 <= item <= 12), 0)
    day = next((item for item in others if 1 <= item <= 31 and item != month), 0)
    return (year, month, day)


def _statement_series(frame: pd.DataFrame | None, key: str) -> pd.Series | None:
    if frame is None or frame.empty:
        return None
    aliases = STATEMENT_ALIASES.get(key, ())
    if not aliases:
        return None
    labels = [(_norm(index), index) for index in frame.index]
    matches: list[Any] = []
    for alias in aliases:
        target = _norm(alias)
        exact = [index for label, index in labels if label == target]
        if exact:
            matches.extend(exact)
            break
    if not matches:
        for alias in aliases:
            target = _norm(alias)
            candidates = [index for label, index in labels if target and (target in label or label in target)]
            if candidates:
                matches.extend(candidates)
                break
    if not matches:
        return None

    best: pd.Series | None = None
    best_count = -1
    for index in matches:
        selected = frame.loc[index]
        if isinstance(selected, pd.DataFrame):
            rows = selected.apply(pd.to_numeric, errors="coerce")
            for _, row in rows.iterrows():
                count = int(row.notna().sum())
                if count > best_count:
                    best, best_count = row, count
        else:
            row = pd.to_numeric(selected, errors="coerce")
            count = int(row.notna().sum())
            if count > best_count:
                best, best_count = row, count
    if best is None:
        return None
    ordered = sorted(best.index, key=_period_key, reverse=True)
    return best.reindex(ordered)


def _values(series: pd.Series | None, count: int | None = None) -> list[float]:
    if series is None:
        return []
    numbers = [float(item) for item in pd.to_numeric(series, errors="coerce").tolist() if pd.notna(item)]
    return numbers if count is None else numbers[:count]


def _latest(series: pd.Series | None) -> float | None:
    values = _values(series, 1)
    return values[0] if values else None


def _sum4(series: pd.Series | None, offset: int = 0) -> float | None:
    values = _values(series)
    chunk = values[offset : offset + 4]
    return float(sum(chunk)) if len(chunk) == 4 else None


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or abs(previous) < 1e-9:
        return None
    return (current / abs(previous) - 1.0) * 100.0


def _ratio(numerator: float | None, denominator: float | None, scale: float = 1.0) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 1e-9:
        return None
    return numerator / denominator * scale


def _avg(*values: float | None) -> float | None:
    available = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(sum(available) / len(available)) if available else None


def _score_higher(value: float | None, bad: float, good: float) -> float | None:
    if value is None:
        return None
    if good <= bad:
        raise ValueError("good must be greater than bad")
    return float(np.clip((value - bad) / (good - bad) * 5.0, 0.0, 5.0))


def _score_lower(value: float | None, good: float, bad: float) -> float | None:
    if value is None:
        return None
    if bad <= good:
        raise ValueError("bad must be greater than good")
    return float(np.clip((bad - value) / (bad - good) * 5.0, 0.0, 5.0))


def _score_target(
    value: float | None,
    ideal_low: float,
    ideal_high: float,
    hard_low: float,
    hard_high: float,
) -> float | None:
    if value is None:
        return None
    if ideal_low <= value <= ideal_high:
        return 5.0
    if value < ideal_low:
        if value <= hard_low:
            return 0.0
        return float(np.clip((value - hard_low) / (ideal_low - hard_low) * 5.0, 0.0, 5.0))
    if value >= hard_high:
        return 0.0
    return float(np.clip((hard_high - value) / (hard_high - ideal_high) * 5.0, 0.0, 5.0))


def _factor(name: str, scores: Iterable[float | None], details: Iterable[str]) -> Factor:
    values = [score for score in scores if score is not None]
    all_scores = list(scores) if not isinstance(scores, list) else scores
    # Iterables may have been consumed above; callers pass lists in practice.
    if not isinstance(scores, list):
        all_scores = values
    total = max(len(all_scores), 1)
    coverage = len(values) / total
    score = round(float(sum(values) / len(values)), 2) if values else None
    detail = " · ".join(item for item in details if item)
    return Factor(name=name, score=score, coverage=round(coverage, 2), detail=detail)


def _factor_list(name: str, scores: list[float | None], details: list[str]) -> Factor:
    values = [score for score in scores if score is not None]
    coverage = len(values) / max(len(scores), 1)
    score = round(float(sum(values) / len(values)), 2) if values else None
    return Factor(name=name, score=score, coverage=round(coverage, 2), detail=" · ".join(details))


def _fmt_pct(value: float | None) -> str:
    return "—" if value is None else f"%{value:+.1f}"


def _fmt_ratio(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}x"


def _classify(symbol: str, sector: str) -> str:
    lowered = sector.casefold()
    if symbol in BANK_SYMBOLS or "bank" in lowered or "banka" in lowered:
        return "BANK"
    if symbol.endswith("GYO") or "reit" in lowered or "gayrimenkul" in lowered or "real estate" in lowered:
        return "GYO"
    return "GENERIC"


def _extract_common(
    balance: pd.DataFrame | None,
    income: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
) -> dict[str, float | None]:
    revenue = _statement_series(income, "revenue")
    operating = _statement_series(income, "operating_profit")
    ebitda = _statement_series(income, "ebitda")
    net_income = _statement_series(income, "net_income")
    cfo = _statement_series(cashflow, "cfo")
    capex = _statement_series(cashflow, "capex")
    assets = _statement_series(balance, "assets")
    equity = _statement_series(balance, "equity")
    current_assets = _statement_series(balance, "current_assets")
    current_liabilities = _statement_series(balance, "current_liabilities")
    cash = _statement_series(balance, "cash")
    short_debt = _statement_series(balance, "short_debt")
    long_debt = _statement_series(balance, "long_debt")

    revenue_ttm = _sum4(revenue)
    revenue_prev = _sum4(revenue, 4)
    operating_ttm = _sum4(operating)
    operating_prev = _sum4(operating, 4)
    ebitda_ttm = _sum4(ebitda)
    net_ttm = _sum4(net_income)
    net_prev = _sum4(net_income, 4)
    cfo_ttm = _sum4(cfo)
    cfo_prev = _sum4(cfo, 4)
    capex_ttm = _sum4(capex)
    latest_assets = _latest(assets)
    latest_equity = _latest(equity)
    latest_cash = _latest(cash)
    short_debt_latest = _latest(short_debt)
    long_debt_latest = _latest(long_debt)
    total_debt = None
    if short_debt_latest is not None or long_debt_latest is not None:
        total_debt = (short_debt_latest or 0.0) + (long_debt_latest or 0.0)
    net_debt = None if total_debt is None else total_debt - (latest_cash or 0.0)
    fcf = None if cfo_ttm is None else cfo_ttm - abs(capex_ttm or 0.0)

    return {
        "revenue_growth": _growth(revenue_ttm, revenue_prev),
        "operating_growth": _growth(operating_ttm, operating_prev),
        "net_income_growth": _growth(net_ttm, net_prev),
        "cfo_growth": _growth(cfo_ttm, cfo_prev),
        "operating_margin": _ratio(operating_ttm, revenue_ttm, 100.0),
        "net_margin": _ratio(net_ttm, revenue_ttm, 100.0),
        "roe": _ratio(net_ttm, latest_equity, 100.0),
        "roa": _ratio(net_ttm, latest_assets, 100.0),
        "current_ratio": _ratio(_latest(current_assets), _latest(current_liabilities)),
        "equity_assets": _ratio(latest_equity, latest_assets, 100.0),
        "net_debt_equity": _ratio(net_debt, latest_equity),
        "cfo_net_income": _ratio(cfo_ttm, net_ttm),
        "fcf_margin": _ratio(fcf, revenue_ttm, 100.0),
        "assets": latest_assets,
        "equity": latest_equity,
        "net_income_ttm": net_ttm,
        "ebitda_ttm": ebitda_ttm,
        "total_debt": total_debt,
        "cash": latest_cash,
    }


def _score_generic(metrics: dict[str, float | None]) -> tuple[Factor, ...]:
    pe = metrics.get("pe")
    pb = metrics.get("pb")
    ev_ebitda = metrics.get("ev_ebitda")
    valuation = _factor_list(
        "Değerleme",
        [
            _score_lower(pe, 7.0, 35.0) if pe is not None and pe > 0 else None,
            _score_lower(pb, 0.8, 6.0) if pb is not None and pb > 0 else None,
            _score_lower(ev_ebitda, 5.0, 24.0) if ev_ebitda is not None and ev_ebitda > 0 else None,
        ],
        [f"F/K {pe:.2f}" if pe and pe > 0 else "F/K N/M", f"PD/DD {pb:.2f}" if pb and pb > 0 else "PD/DD —"],
    )
    growth = _factor_list(
        "Büyüme",
        [
            _score_higher(metrics.get("revenue_growth"), -10.0, 30.0),
            _score_higher(metrics.get("operating_growth"), -15.0, 35.0),
            _score_higher(metrics.get("net_income_growth"), -20.0, 40.0),
        ],
        [
            f"Satış {_fmt_pct(metrics.get('revenue_growth'))}",
            f"Net kâr {_fmt_pct(metrics.get('net_income_growth'))}",
        ],
    )
    profitability = _factor_list(
        "Kârlılık",
        [
            _score_higher(metrics.get("roe"), 0.0, 30.0),
            _score_higher(metrics.get("roa"), 0.0, 12.0),
            _score_higher(metrics.get("operating_margin"), 0.0, 25.0),
            _score_higher(metrics.get("net_margin"), 0.0, 20.0),
        ],
        [f"ROE {_fmt_pct(metrics.get('roe'))}", f"Net marj {_fmt_pct(metrics.get('net_margin'))}"],
    )
    balance = _factor_list(
        "Bilanço Sağlığı",
        [
            _score_target(metrics.get("current_ratio"), 1.3, 2.8, 0.6, 6.0),
            _score_lower(metrics.get("net_debt_equity"), 0.0, 2.0),
            _score_higher(metrics.get("equity_assets"), 15.0, 60.0),
        ],
        [
            f"Cari oran {_fmt_ratio(metrics.get('current_ratio'))}",
            f"Net borç/özk. {_fmt_ratio(metrics.get('net_debt_equity'))}",
        ],
    )
    cash = _factor_list(
        "Nakit Akışı",
        [
            _score_target(metrics.get("cfo_net_income"), 0.8, 2.2, -0.5, 5.0),
            _score_higher(metrics.get("fcf_margin"), -10.0, 20.0),
            _score_higher(metrics.get("cfo_growth"), -20.0, 40.0),
        ],
        [
            f"Nakit/kâr {_fmt_ratio(metrics.get('cfo_net_income'))}",
            f"SNA büyüme {_fmt_pct(metrics.get('cfo_growth'))}",
        ],
    )
    return valuation, growth, profitability, balance, cash


def _score_bank(
    metrics: dict[str, float | None],
    balance: pd.DataFrame | None,
    income: pd.DataFrame | None,
) -> tuple[Factor, ...]:
    net_interest = _statement_series(income, "net_interest_income")
    interest_income = _statement_series(income, "interest_income")
    interest_expense = _statement_series(income, "interest_expense")
    operating_expense = _statement_series(income, "operating_expense")
    loans = _statement_series(balance, "loans")
    deposits = _statement_series(balance, "deposits")
    assets = _statement_series(balance, "assets")
    equity = _statement_series(balance, "equity")

    net_interest_growth = _growth(_sum4(net_interest), _sum4(net_interest, 4))
    interest_income_growth = _growth(_sum4(interest_income), _sum4(interest_income, 4))
    interest_expense_growth = _growth(abs(_sum4(interest_expense) or 0.0), abs(_sum4(interest_expense, 4) or 0.0))
    expense_growth = _growth(abs(_sum4(operating_expense) or 0.0), abs(_sum4(operating_expense, 4) or 0.0))
    loans_growth = _growth(_latest(loans), _values(loans, 5)[4] if len(_values(loans, 5)) == 5 else None)
    deposits_growth = _growth(_latest(deposits), _values(deposits, 5)[4] if len(_values(deposits, 5)) == 5 else None)
    assets_growth = _growth(_latest(assets), _values(assets, 5)[4] if len(_values(assets, 5)) == 5 else None)
    equity_growth = _growth(_latest(equity), _values(equity, 5)[4] if len(_values(equity, 5)) == 5 else None)
    loans_deposits = _ratio(_latest(loans), _latest(deposits))

    metrics.update(
        {
            "net_interest_growth": net_interest_growth,
            "interest_income_growth": interest_income_growth,
            "interest_expense_growth": interest_expense_growth,
            "operating_expense_growth": expense_growth,
            "loans_growth": loans_growth,
            "deposits_growth": deposits_growth,
            "assets_growth": assets_growth,
            "equity_growth": equity_growth,
            "loans_deposits": loans_deposits,
        }
    )

    income_structure = _factor_list(
        "Gelir / Gider Yapısı",
        [
            _score_higher(net_interest_growth, -15.0, 35.0),
            _score_higher(interest_income_growth, -10.0, 35.0),
            _score_lower(
                None if interest_expense_growth is None or interest_income_growth is None else interest_expense_growth - interest_income_growth,
                -20.0,
                30.0,
            ),
            _score_lower(
                None if expense_growth is None or net_interest_growth is None else expense_growth - net_interest_growth,
                -20.0,
                30.0,
            ),
        ],
        [f"Net faiz {_fmt_pct(net_interest_growth)}", f"Faiz geliri {_fmt_pct(interest_income_growth)}"],
    )
    growth = _factor_list(
        "Büyüme",
        [
            _score_higher(loans_growth, -5.0, 35.0),
            _score_higher(deposits_growth, -5.0, 35.0),
            _score_higher(assets_growth, -5.0, 30.0),
            _score_higher(metrics.get("net_income_growth"), -20.0, 40.0),
        ],
        [f"Kredi {_fmt_pct(loans_growth)}", f"Aktif {_fmt_pct(assets_growth)}"],
    )
    profitability = _factor_list(
        "Kârlılık",
        [
            _score_higher(metrics.get("roe"), 5.0, 35.0),
            _score_higher(metrics.get("roa"), 0.2, 4.0),
            _score_higher(metrics.get("net_income_growth"), -20.0, 40.0),
        ],
        [f"ROE {_fmt_pct(metrics.get('roe'))}", f"ROA {_fmt_pct(metrics.get('roa'))}"],
    )
    capital = _factor_list(
        "Sermaye Gücü",
        [
            _score_higher(metrics.get("equity_assets"), 5.0, 14.0),
            _score_higher(equity_growth, -5.0, 30.0),
        ],
        [f"Özk./aktif {_fmt_pct(metrics.get('equity_assets'))}", f"Özk. büyüme {_fmt_pct(equity_growth)}"],
    )
    balance_structure = _factor_list(
        "Bilanço Yapısı",
        [
            _score_target(loans_deposits, 0.75, 1.05, 0.35, 1.45),
            _score_higher(deposits_growth, -5.0, 35.0),
            _score_higher(assets_growth, -5.0, 30.0),
        ],
        [f"Kredi/mevduat {_fmt_ratio(loans_deposits)}", f"Mevduat {_fmt_pct(deposits_growth)}"],
    )
    return income_structure, growth, profitability, capital, balance_structure


def _score_gyo(metrics: dict[str, float | None]) -> tuple[Factor, ...]:
    pb = metrics.get("pb")
    pe = metrics.get("pe")
    valuation = _factor_list(
        "Değerleme",
        [
            _score_lower(pb, 0.45, 2.0) if pb is not None and pb > 0 else None,
            _score_lower(pe, 6.0, 30.0) if pe is not None and pe > 0 else None,
        ],
        [f"PD/DD {pb:.2f}" if pb and pb > 0 else "PD/DD —", f"F/K {pe:.2f}" if pe and pe > 0 else "F/K N/M"],
    )
    growth = _factor_list(
        "Büyüme",
        [
            _score_higher(metrics.get("revenue_growth"), -10.0, 30.0),
            _score_higher(metrics.get("net_income_growth"), -20.0, 40.0),
        ],
        [f"Gelir {_fmt_pct(metrics.get('revenue_growth'))}", f"Net kâr {_fmt_pct(metrics.get('net_income_growth'))}"],
    )
    profitability = _factor_list(
        "Kârlılık",
        [
            _score_higher(metrics.get("roe"), 0.0, 25.0),
            _score_higher(metrics.get("roa"), 0.0, 10.0),
            _score_higher(metrics.get("net_margin"), 0.0, 35.0),
        ],
        [f"ROE {_fmt_pct(metrics.get('roe'))}", f"Net marj {_fmt_pct(metrics.get('net_margin'))}"],
    )
    capital = _factor_list(
        "Sermaye / Borç",
        [
            _score_higher(metrics.get("equity_assets"), 25.0, 75.0),
            _score_lower(metrics.get("net_debt_equity"), 0.0, 1.5),
        ],
        [
            f"Özk./aktif {_fmt_pct(metrics.get('equity_assets'))}",
            f"Net borç/özk. {_fmt_ratio(metrics.get('net_debt_equity'))}",
        ],
    )
    cash = _factor_list(
        "Nakit / Temettü",
        [
            _score_target(metrics.get("cfo_net_income"), 0.7, 2.5, -0.5, 5.0),
            _score_higher(metrics.get("dividend_yield"), 0.0, 8.0),
        ],
        [
            f"Nakit/kâr {_fmt_ratio(metrics.get('cfo_net_income'))}",
            f"Temettü {_fmt_pct(metrics.get('dividend_yield'))}",
        ],
    )
    return valuation, growth, profitability, capital, cash


def _insights(profile: str, factors: tuple[Factor, ...], metrics: dict[str, float | None]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    positives: list[str] = []
    risks: list[str] = []
    for factor in factors:
        if factor.score is None:
            continue
        if factor.score >= 3.6:
            positives.append(f"{factor.name}: güçlü görünüm ({factor.score:.1f}/5).")
        elif factor.score <= 1.8:
            risks.append(f"{factor.name}: zayıf görünüm ({factor.score:.1f}/5).")

    if metrics.get("net_income_growth") is not None:
        growth = float(metrics["net_income_growth"])
        if growth >= 20:
            positives.append(f"Net kâr yıllık bazda güçlü büyüyor ({growth:+.1f}%).")
        elif growth <= -15:
            risks.append(f"Net kâr yıllık bazda geriliyor ({growth:+.1f}%).")
    if profile != "BANK" and metrics.get("net_debt_equity") is not None:
        leverage = float(metrics["net_debt_equity"])
        if leverage > 1.5:
            risks.append(f"Net borç/özkaynak yüksek ({leverage:.2f}x).")
        elif leverage <= 0.2:
            positives.append(f"Net borçluluk düşük ({leverage:.2f}x).")
    if profile == "BANK" and metrics.get("net_interest_growth") is not None:
        growth = float(metrics["net_interest_growth"])
        if growth >= 20:
            positives.append(f"Net faiz geliri güçlü büyüyor ({growth:+.1f}%).")
        elif growth <= -10:
            risks.append(f"Net faiz geliri zayıflıyor ({growth:+.1f}%).")

    def unique(items: list[str]) -> tuple[str, ...]:
        seen: set[str] = set()
        result: list[str] = []
        for item in items:
            if item not in seen:
                result.append(item)
                seen.add(item)
        return tuple(result[:3])

    return unique(positives), unique(risks)


def _clean_multiple(value: float | None) -> float | None:
    if value is None:
        return None
    # Some providers use -100/-999 style boundary values as sentinels.
    if value <= -90 or abs(value) >= 10000:
        return None
    return value


def _provider_multiple(fast: dict[str, Any], info: dict[str, Any], *names: str) -> float | None:
    return _clean_multiple(_pick(fast, *names) or _pick(info, *names))


def _market_cap(price: float | None, fast: dict[str, Any], info: dict[str, Any]) -> float | None:
    market_cap = _pick(fast, "market_cap", "marketCap", "market_value")
    if market_cap is None:
        market_cap = _pick(info, "marketCap", "market_cap", "marketValue")
    if market_cap is not None and market_cap > 0:
        return market_cap
    shares = _pick(fast, "shares_outstanding", "sharesOutstanding", "shares")
    if shares is None:
        shares = _pick(info, "sharesOutstanding", "shares_outstanding", "impliedSharesOutstanding")
    if price is not None and price > 0 and shares is not None and shares > 0:
        return price * shares
    return None


def _derive_multiples(
    metrics: dict[str, float | None],
    price: float | None,
    fast: dict[str, Any],
    info: dict[str, Any],
) -> dict[str, float | None]:
    """Prefer auditable raw calculations; use provider ratios only when raw inputs are absent."""
    market_cap = _market_cap(price, fast, info)
    net_income = metrics.get("net_income_ttm")
    equity = metrics.get("equity")
    debt = metrics.get("total_debt")
    cash = metrics.get("cash")
    ebitda = metrics.get("ebitda_ttm")

    provider_pe = _provider_multiple(fast, info, "pe_ratio", "pe", "trailingPE")
    provider_pb = _provider_multiple(fast, info, "price_to_book", "pb", "priceToBook")
    provider_ev_ebitda = _provider_multiple(fast, info, "enterpriseToEbitda", "evToEbitda", "ev_ebitda")

    if market_cap is not None and net_income is not None:
        pe = market_cap / net_income if net_income > 0 else None
    else:
        pe = provider_pe

    if market_cap is not None and equity is not None:
        pb = market_cap / equity if equity > 0 else None
    else:
        pb = provider_pb

    if market_cap is not None and debt is not None and cash is not None and ebitda is not None:
        enterprise_value = market_cap + debt - cash
        ev_ebitda = enterprise_value / ebitda if ebitda > 0 else None
    else:
        ev_ebitda = provider_ev_ebitda

    return {"pe": _clean_multiple(pe), "pb": _clean_multiple(pb), "ev_ebitda": _clean_multiple(ev_ebitda)}


def build_fundamental_report(symbol: str) -> FundamentalReport:
    """Fetch current fundamentals and build a sector-aware 0-5 scorecard."""
    import borsapy as bp

    ticker = symbol.strip().upper().removesuffix(".IS")
    stock = bp.Ticker(ticker)
    try:
        fast = dict(stock.fast_info or {})
    except Exception:  # noqa: BLE001 -- provider payloads may vary by symbol
        fast = {}
    try:
        info = dict(stock.info or {})
    except Exception:  # noqa: BLE001
        info = {}

    sector = _pick_text(info, "sector", "industry", "sektor") or "Sektör bilgisi yok"
    company_name = _pick_text(info, "longName", "shortName", "companyName", "name") or ticker
    profile = _classify(ticker, sector)
    financial_group = "UFRS" if profile == "BANK" else "XI_29"

    balance = stock.get_balance_sheet(quarterly=True, financial_group=financial_group, last_n=8)
    income = stock.get_income_stmt(quarterly=True, financial_group=financial_group, last_n=8)
    cashflow = None
    if profile != "BANK":
        try:
            cashflow = stock.get_cashflow(quarterly=True, financial_group=financial_group, last_n=8)
        except Exception:  # noqa: BLE001 -- some issuers do not expose cashflow for every period
            cashflow = None

    metrics = _extract_common(balance, income, cashflow)
    price = _pick(fast, "last_price", "last", "price") or _pick(info, "last", "lastPrice", "price")
    metrics.update(_derive_multiples(metrics, price, fast, info))
    metrics["dividend_yield"] = _pick(info, "dividendYield", "dividend_yield")
    dividend = metrics.get("dividend_yield")
    if dividend is not None and 0 <= dividend <= 1.0:
        metrics["dividend_yield"] = dividend * 100.0

    if profile == "BANK":
        factors = _score_bank(metrics, balance, income)
        note = "Sermaye Gücü, özkaynak/aktif ve özkaynak büyümesine dayalıdır; resmi SYR değildir."
    elif profile == "GYO":
        factors = _score_gyo(metrics)
        note = "GYO değerlemesinde NAV/portföy ekspertiz verisi yoksa PD/DD ve bilanço metrikleri kullanılır."
    else:
        factors = _score_generic(metrics)
        note = "Skorlar bilanço, gelir tablosu, nakit akışı ve güncel çarpanların birlikte okunmasına dayanır."

    available = [factor.score for factor in factors if factor.score is not None]
    overall = round(float(sum(available) / len(available)), 2) if available else None
    coverage = round(sum(factor.coverage for factor in factors) / len(factors), 2) if factors else 0.0
    positives, risks = _insights(profile, factors, metrics)

    return FundamentalReport(
        symbol=ticker,
        company_name=company_name,
        price=price,
        sector=sector,
        profile=profile,
        overall_score=overall,
        coverage=coverage,
        factors=factors,
        positives=positives,
        risks=risks,
        metrics=metrics,
        note=note,
    )