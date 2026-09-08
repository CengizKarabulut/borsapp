from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Protocol

import pandas as pd

ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": ("total revenue", "revenue", "sales revenue", "net sales", "hasılat"),
    "gross_profit": ("gross profit", "brüt kar"),
    "operating_profit": ("operating income", "operating profit", "faaliyet karı"),
    "ebitda": ("ebitda", "normalized ebitda", "favök"),
    "net_income": ("net income", "net profit", "net dönem karı", "ana ortaklık payları"),
    "cfo": ("operating cash flow", "cash flow from continuing operating activities", "işletme faaliyetlerinden nakit akışları"),
    "capex": ("capital expenditure", "capital expenditures", "purchase of property plant equipment", "maddi ve maddi olmayan duran varlık alımları"),
    "cash": ("cash cash equivalents and short term investments", "cash and cash equivalents", "nakit ve nakit benzerleri"),
    "assets": ("total assets", "toplam varlıklar", "aktif toplamı"),
    "liabilities": ("total liabilities net minority interest", "total liabilities", "toplam yükümlülükler"),
    "current_assets": ("current assets", "total current assets", "dönen varlıklar"),
    "current_liabilities": ("current liabilities", "total current liabilities", "kısa vadeli yükümlülükler"),
    "equity": ("stockholders equity", "total equity gross minority interest", "total equity", "özkaynaklar"),
    "short_debt": ("current debt", "short term debt", "short term borrowings", "kısa vadeli borçlanmalar"),
    "long_debt": ("long term debt", "long term debt and capital lease obligation", "long term borrowings", "uzun vadeli borçlanmalar"),
}


@dataclass(frozen=True)
class FinancialSnapshot:
    symbol: str
    as_of: datetime
    company_name: str | None
    sector: str | None
    currency: str | None
    metrics: dict[str, float | None]
    metric_sources: dict[str, str]
    statement_periods: tuple[str, ...]
    providers_used: tuple[str, ...]
    errors: tuple[str, ...] = ()

    @property
    def coverage(self) -> float:
        required = (
            "revenue_ttm",
            "net_income_ttm",
            "assets",
            "equity",
            "cash",
            "total_debt",
            "cfo_ttm",
            "market_cap",
        )
        return sum(self.metrics.get(key) is not None for key in required) / len(required)


class FinancialDataProvider(Protocol):
    provider_id: str

    def fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot: ...


def _norm(value: Any) -> str:
    text = str(value).strip().casefold().translate(str.maketrans("çğıöşü", "cgiosu"))
    return re.sub(r"[^a-z0-9]+", "", text)


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _period(value: Any) -> datetime | None:
    try:
        parsed = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().replace(tzinfo=None)


def _filter_as_of(frame: pd.DataFrame | None, as_of: datetime) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return frame
    allowed = []
    cutoff = as_of.replace(tzinfo=None)
    for column in frame.columns:
        parsed = _period(column)
        if parsed is None or parsed <= cutoff:
            allowed.append(column)
    return frame.loc[:, allowed]


def _series(frame: pd.DataFrame | None, key: str) -> list[float]:
    if frame is None or frame.empty:
        return []
    labels = [(_norm(index), index) for index in frame.index]
    selected: Any | None = None
    for alias in ALIASES[key]:
        target = _norm(alias)
        exact = [index for label, index in labels if label == target]
        if exact:
            selected = exact[0]
            break
    if selected is None:
        for alias in ALIASES[key]:
            target = _norm(alias)
            partial = [index for label, index in labels if target in label or label in target]
            if partial:
                selected = partial[0]
                break
    if selected is None:
        return []
    row = frame.loc[selected]
    if isinstance(row, pd.DataFrame):
        row = max((item for _, item in row.iterrows()), key=lambda item: int(item.notna().sum()))
    pairs = []
    for column, value in row.items():
        numeric = _finite(value)
        if numeric is not None:
            pairs.append((_period(column) or datetime.min, numeric))
    return [value for _, value in sorted(pairs, reverse=True)]


def _latest(values: list[float], lag: int = 0) -> float | None:
    return values[lag] if len(values) > lag else None


def _sum4(values: list[float], offset: int = 0) -> float | None:
    selected = values[offset : offset + 4]
    return sum(selected) if len(selected) == 4 else None


def _ratio(left: float | None, right: float | None, scale: float = 1.0) -> float | None:
    if left is None or right is None or abs(right) < 1e-12:
        return None
    return left / right * scale


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or abs(previous) < 1e-12:
        return None
    return (current / abs(previous) - 1.0) * 100.0


def _pick(mapping: dict[str, Any], *keys: str) -> float | None:
    normalised = {_norm(key): value for key, value in mapping.items()}
    for key in keys:
        value = _finite(mapping.get(key))
        if value is None:
            value = _finite(normalised.get(_norm(key)))
        if value is not None:
            return value
    return None


def _snapshot_from_frames(
    *,
    provider_id: str,
    symbol: str,
    as_of: datetime,
    balance: pd.DataFrame | None,
    income: pd.DataFrame | None,
    cashflow: pd.DataFrame | None,
    info: dict[str, Any],
    fast: dict[str, Any],
) -> FinancialSnapshot:
    balance = _filter_as_of(balance, as_of)
    income = _filter_as_of(income, as_of)
    cashflow = _filter_as_of(cashflow, as_of)
    values = {
        key: _series(frame, key)
        for key, frame in {
            "revenue": income,
            "gross_profit": income,
            "operating_profit": income,
            "ebitda": income,
            "net_income": income,
            "cfo": cashflow,
            "capex": cashflow,
            "cash": balance,
            "assets": balance,
            "liabilities": balance,
            "current_assets": balance,
            "current_liabilities": balance,
            "equity": balance,
            "short_debt": balance,
            "long_debt": balance,
        }.items()
    }
    revenue = _sum4(values["revenue"])
    previous_revenue = _sum4(values["revenue"], 4)
    gross_profit = _sum4(values["gross_profit"])
    operating_profit = _sum4(values["operating_profit"])
    ebitda = _sum4(values["ebitda"])
    net_income = _sum4(values["net_income"])
    previous_net_income = _sum4(values["net_income"], 4)
    cfo = _sum4(values["cfo"])
    capex = _sum4(values["capex"])
    assets = _latest(values["assets"])
    equity = _latest(values["equity"])
    liabilities = _latest(values["liabilities"])
    if liabilities is None and assets is not None and equity is not None:
        liabilities = assets - equity
    cash = _latest(values["cash"])
    debt_parts = (_latest(values["short_debt"]), _latest(values["long_debt"]))
    total_debt = sum(value or 0.0 for value in debt_parts) if any(value is not None for value in debt_parts) else None
    market_cap = _pick(fast, "market_cap", "marketCap") or _pick(info, "marketCap", "market_cap")
    metrics = {
        "revenue_ttm": revenue,
        "revenue_growth": _growth(revenue, previous_revenue),
        "gross_margin": _ratio(gross_profit, revenue, 100.0),
        "operating_margin": _ratio(operating_profit, revenue, 100.0),
        "net_margin": _ratio(net_income, revenue, 100.0),
        "net_income_ttm": net_income,
        "net_income_growth": _growth(net_income, previous_net_income),
        "ebitda_ttm": ebitda,
        "cfo_ttm": cfo,
        "fcf_ttm": None if cfo is None else cfo - abs(capex or 0.0),
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "cash": cash,
        "total_debt": total_debt,
        "net_debt": None if total_debt is None else total_debt - (cash or 0.0),
        "current_ratio": _ratio(_latest(values["current_assets"]), _latest(values["current_liabilities"])),
        "debt_equity": _ratio(total_debt, equity),
        "roe": _ratio(net_income, equity, 100.0),
        "roa": _ratio(net_income, assets, 100.0),
        "market_cap": market_cap,
        "pe": _ratio(market_cap, net_income) if net_income is not None and net_income > 0 else _pick(info, "trailingPE", "pe_ratio"),
        "pb": _ratio(market_cap, equity) if equity is not None and equity > 0 else _pick(info, "priceToBook", "pb"),
        "ev_ebitda": (
            _ratio(market_cap + total_debt - (cash or 0.0), ebitda)
            if market_cap is not None and total_debt is not None and ebitda is not None and ebitda > 0
            else _pick(info, "enterpriseToEbitda", "ev_ebitda")
        ),
    }
    periods = set()
    for frame in (balance, income, cashflow):
        if frame is not None:
            periods.update(str(column) for column in frame.columns)
    company_name = next((str(info[key]) for key in ("longName", "shortName", "companyName", "name") if info.get(key)), None)
    sector = next((str(info[key]) for key in ("sector", "industry", "sektor") if info.get(key)), None)
    currency = next((str(info[key]) for key in ("currency", "financialCurrency") if info.get(key)), None)
    return FinancialSnapshot(
        symbol=symbol,
        as_of=as_of,
        company_name=company_name,
        sector=sector,
        currency=currency,
        metrics=metrics,
        metric_sources={key: provider_id for key, value in metrics.items() if value is not None},
        statement_periods=tuple(sorted(periods, reverse=True)),
        providers_used=(provider_id,),
    )


class BorsapyKapFinancialProvider:
    """Primary BIST statement adapter. Borsapy exposes the public issuer statements."""

    provider_id = "borsapy:public_bist_statements"

    def fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot:
        import borsapy as bp

        canonical = symbol.strip().upper().removesuffix(".IS")
        ticker = bp.Ticker(canonical)
        try:
            info = dict(ticker.info or {})
        except Exception:
            info = {}
        try:
            fast = dict(ticker.fast_info or {})
        except Exception:
            fast = {}
        sector = str(info.get("sector") or info.get("industry") or "").casefold()
        group = "UFRS" if "bank" in sector or "banka" in sector else "XI_29"
        balance = ticker.get_balance_sheet(quarterly=True, financial_group=group, last_n=8)
        income = ticker.get_income_stmt(quarterly=True, financial_group=group, last_n=8)
        try:
            cashflow = ticker.get_cashflow(quarterly=True, financial_group=group, last_n=8)
        except Exception:
            cashflow = None
        return _snapshot_from_frames(
            provider_id=self.provider_id,
            symbol=canonical,
            as_of=as_of,
            balance=balance,
            income=income,
            cashflow=cashflow,
            info=info,
            fast=fast,
        )


class YFinanceFinancialProvider:
    provider_id = "yfinance:quarterly_statements"

    def fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot:
        import yfinance as yf

        canonical = symbol.strip().upper().removesuffix(".IS")
        ticker = yf.Ticker(f"{canonical}.IS")
        try:
            info = dict(ticker.info or {})
        except Exception:
            info = {}
        try:
            fast = dict(ticker.fast_info or {})
        except Exception:
            fast = {}
        return _snapshot_from_frames(
            provider_id=self.provider_id,
            symbol=canonical,
            as_of=as_of,
            balance=ticker.quarterly_balance_sheet,
            income=ticker.quarterly_income_stmt,
            cashflow=ticker.quarterly_cash_flow,
            info=info,
            fast=fast,
        )


class FinancialProviderChain:
    def __init__(self, providers: tuple[FinancialDataProvider, ...]) -> None:
        if not providers:
            raise ValueError("En az bir finansal veri sağlayıcısı gereklidir")
        self.providers = providers

    def fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot | None:
        snapshots: list[FinancialSnapshot] = []
        errors: list[str] = []
        for provider in self.providers:
            try:
                snapshots.append(provider.fetch(symbol, as_of=as_of))
            except Exception as exc:
                errors.append(f"{provider.provider_id}:{type(exc).__name__}")
        if not snapshots:
            return None
        primary = snapshots[0]
        metrics = dict(primary.metrics)
        sources = dict(primary.metric_sources)
        providers_used = list(primary.providers_used)
        periods = set(primary.statement_periods)
        for fallback in snapshots[1:]:
            providers_used.extend(fallback.providers_used)
            periods.update(fallback.statement_periods)
            for key, value in fallback.metrics.items():
                if metrics.get(key) is None and value is not None:
                    metrics[key] = value
                    sources[key] = fallback.metric_sources.get(key, fallback.providers_used[0])
        return replace(
            primary,
            company_name=primary.company_name or next((item.company_name for item in snapshots[1:] if item.company_name), None),
            sector=primary.sector or next((item.sector for item in snapshots[1:] if item.sector), None),
            currency=primary.currency or next((item.currency for item in snapshots[1:] if item.currency), None),
            metrics=metrics,
            metric_sources=sources,
            statement_periods=tuple(sorted(periods, reverse=True)),
            providers_used=tuple(dict.fromkeys(providers_used)),
            errors=tuple(errors),
        )
