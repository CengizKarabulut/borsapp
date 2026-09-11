from __future__ import annotations

import calendar
import math
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from market_intelligence.fundamentals.text_quality import prefer_turkish_name

ALIASES: dict[str, tuple[str, ...]] = {
    "revenue": (
        "total revenue",
        "revenue",
        "sales revenue",
        "net sales",
        "hasılat",
        "satış gelirleri",
    ),
    "gross_profit": ("gross profit", "brüt kar"),
    "operating_profit": ("operating income", "operating profit", "faaliyet karı"),
    "ebitda": ("ebitda", "normalized ebitda", "favök"),
    "depreciation": (
        "depreciation and amortization",
        "depreciation amortization depletion",
        "amortisman ve itfa gideri ile ilgili düzeltmeler",
    ),
    "receivables": ("accounts receivable", "ticari alacaklar"),
    "inventory": ("inventory", "inventories", "stoklar"),
    "payables": ("accounts payable", "ticari borçlar"),
    "net_income": ("net income", "net profit", "net dönem karı", "ana ortaklık payları"),
    "cfo": (
        "operating cash flow",
        "cash flow from continuing operating activities",
        "işletme faaliyetlerinden nakit akışları",
    ),
    "capex": (
        "capital expenditure",
        "capital expenditures",
        "purchase of property plant equipment",
        "maddi ve maddi olmayan duran varlık alımları",
    ),
    "cash": (
        "cash cash equivalents and short term investments",
        "cash and cash equivalents",
        "nakit ve nakit benzerleri",
    ),
    "assets": ("total assets", "toplam varlıklar", "aktif toplamı"),
    "liabilities": (
        "total liabilities net minority interest",
        "total liabilities",
        "toplam yükümlülükler",
    ),
    "current_assets": ("current assets", "total current assets", "dönen varlıklar"),
    "current_liabilities": (
        "current liabilities",
        "total current liabilities",
        "kısa vadeli yükümlülükler",
    ),
    "equity": (
        "stockholders equity",
        "total equity gross minority interest",
        "total equity",
        "özkaynaklar",
    ),
    "short_debt": (
        "current debt",
        "short term debt",
        "short term borrowings",
        "kısa vadeli borçlanmalar",
    ),
    "long_debt": (
        "long term debt",
        "long term debt and capital lease obligation",
        "long term borrowings",
        "uzun vadeli borçlanmalar",
    ),
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
    series: dict[str, tuple[float, ...]] = field(default_factory=dict)
    metadata: dict[str, str | float | None] = field(default_factory=dict)
    flow_period: datetime | None = None

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
    quarter = re.fullmatch(r"(\d{4})\s*Q([1-4])", str(value).strip(), re.IGNORECASE)
    if quarter:
        year = int(quarter.group(1))
        month = int(quarter.group(2)) * 3
        return datetime(year, month, calendar.monthrange(year, month)[1])
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


FLOW_KEYS = frozenset(
    {
        "revenue",
        "gross_profit",
        "operating_profit",
        "ebitda",
        "net_income",
        "cfo",
        "capex",
        "depreciation",
    }
)


def _pairs(frame: pd.DataFrame | None, key: str) -> list[tuple[datetime, float]]:
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
        parsed = _period(column)
        if numeric is not None and parsed is not None:
            pairs.append((parsed, numeric))
    return sorted(pairs, key=lambda item: item[0], reverse=True)


def _series(frame: pd.DataFrame | None, key: str) -> list[float]:
    return [value for _, value in _pairs(frame, key)]


def _quarter(period: datetime) -> tuple[int, int]:
    return period.year, (period.month - 1) // 3 + 1


def _shift_quarter(year: int, quarter: int, delta: int) -> tuple[int, int]:
    absolute = year * 4 + quarter - 1 + delta
    shifted_year, shifted_zero_based_quarter = divmod(absolute, 4)
    return shifted_year, shifted_zero_based_quarter + 1


def _at(pairs: list[tuple[datetime, float]], year: int, quarter: int) -> float | None:
    return next(
        (value for period, value in pairs if _quarter(period) == (year, quarter)),
        None,
    )


def _ttm_cumulative(
    pairs: list[tuple[datetime, float]],
    lag_quarters: int = 0,
) -> float | None:
    """Build TTM from cumulative YTD flows using exact calendar quarters."""

    if lag_quarters < 0:
        raise ValueError("lag_quarters negatif olamaz")
    ordered = sorted(pairs, key=lambda item: item[0], reverse=True)
    if not ordered:
        return None
    latest_year, latest_quarter = _quarter(ordered[0][0])
    year, quarter = _shift_quarter(latest_year, latest_quarter, -lag_quarters)
    value = _at(ordered, year, quarter)
    if value is None:
        return None
    if quarter == 4:
        return value
    prior_full_year = _at(ordered, year - 1, 4)
    prior_same_period = _at(ordered, year - 1, quarter)
    if prior_full_year is None or prior_same_period is None:
        return None
    return value + prior_full_year - prior_same_period


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
    cumulative_flows: bool = False,
    common_purchasing_power: bool = True,
) -> FinancialSnapshot:
    balance = _filter_as_of(balance, as_of)
    income = _filter_as_of(income, as_of)
    cashflow = _filter_as_of(cashflow, as_of)
    dated = {
        key: _pairs(frame, key)
        for key, frame in {
            "revenue": income,
            "gross_profit": income,
            "operating_profit": income,
            "ebitda": income,
            "net_income": income,
            "cfo": cashflow,
            "capex": cashflow,
            "depreciation": cashflow,
            "receivables": balance,
            "inventory": balance,
            "payables": balance,
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
    values = {key: [value for _, value in pairs] for key, pairs in dated.items()}
    flow_anchor = max(
        (pairs[0][0] for key, pairs in dated.items() if key in FLOW_KEYS and pairs), default=None
    )
    balance_anchor = max(
        (pairs[0][0] for key, pairs in dated.items() if key not in FLOW_KEYS and pairs),
        default=None,
    )

    def balance_value(key):
        return next((value for period, value in dated[key] if period == balance_anchor), None)

    def flow(key: str, lag: int = 0) -> float | None:
        if key not in FLOW_KEYS:
            raise ValueError(f"TTM yalnız akım kalemlerine uygulanabilir: {key}")
        if not dated[key] or dated[key][0][0] != flow_anchor:
            return None
        if not common_purchasing_power:
            # An annual cumulative amount is already a complete flow; do not
            # construct a rolling total from dates whose monetary basis is unknown.
            if cumulative_flows and lag == 0 and _quarter(flow_anchor)[1] == 4:
                return dated[key][0][1]
            return None
        if cumulative_flows:
            return _ttm_cumulative(dated[key], lag)
        year, quarter = _quarter(flow_anchor)
        expected = [
            _at(dated[key], *_shift_quarter(year, quarter, -offset))
            for offset in range(lag, lag + 4)
        ]
        return sum(expected) if all(value is not None for value in expected) else None

    revenue = flow("revenue")
    previous_revenue = flow("revenue", 4)
    gross_profit = flow("gross_profit")
    previous_gross_profit = flow("gross_profit", 4)
    operating_profit = flow("operating_profit")
    previous_operating_profit = flow("operating_profit", 4)
    depreciation = flow("depreciation")
    ebitda = flow("ebitda")
    previous_ebitda = flow("ebitda", 4)
    net_income = flow("net_income")
    previous_net_income = flow("net_income", 4)
    cfo = flow("cfo")
    previous_cfo = flow("cfo", 4)
    capex = flow("capex")
    assets = balance_value("assets")
    equity = balance_value("equity")
    liabilities = balance_value("liabilities")
    if liabilities is None and assets is not None and equity is not None:
        liabilities = assets - equity
    cash = balance_value("cash")
    debt_parts = (balance_value("short_debt"), balance_value("long_debt"))
    total_debt = sum(debt_parts) if all(value is not None for value in debt_parts) else None
    net_debt = total_debt - cash if total_debt is not None and cash is not None else None
    market_cap = _pick(fast, "market_cap", "marketCap") or _pick(info, "marketCap", "market_cap")
    enterprise_value = _pick(info, "enterpriseValue", "enterprise_value")
    shares_outstanding = _pick(
        fast,
        "shares_outstanding",
        "sharesOutstanding",
    ) or _pick(info, "sharesOutstanding", "impliedSharesOutstanding")
    fcf = cfo - abs(capex) if cfo is not None and capex is not None else None
    metrics = {
        "revenue_ttm": revenue,
        "revenue_growth": _growth(revenue, previous_revenue),
        "gross_profit_growth": _growth(gross_profit, previous_gross_profit),
        "operating_profit_growth": _growth(operating_profit, previous_operating_profit),
        "ebitda_growth": _growth(ebitda, previous_ebitda),
        "gross_margin": _ratio(gross_profit, revenue, 100.0),
        "operating_margin": _ratio(operating_profit, revenue, 100.0),
        "ebitda_margin": _ratio(ebitda, revenue, 100.0),
        "net_margin": _ratio(net_income, revenue, 100.0),
        "net_income_ttm": net_income,
        "net_income_growth": _growth(net_income, previous_net_income),
        "ebitda_ttm": ebitda,
        "operating_profit_ttm": operating_profit,
        "depreciation_ttm": depreciation,
        "working_capital": (
            balance_value("receivables") + balance_value("inventory") - balance_value("payables")
            if all(
                balance_value(key) is not None for key in ("receivables", "inventory", "payables")
            )
            else None
        ),
        "cfo_ttm": cfo,
        "cfo_growth": _growth(cfo, previous_cfo),
        "cfo_net_income": _ratio(cfo, net_income),
        "capex_ttm": capex,
        "fcf_ttm": fcf,
        "fcf_margin": _ratio(fcf, revenue, 100.0),
        "assets": assets,
        "liabilities": liabilities,
        "equity": equity,
        "cash": cash,
        "total_debt": total_debt,
        "net_debt": net_debt,
        "current_ratio": _ratio(
            balance_value("current_assets"), balance_value("current_liabilities")
        ),
        "debt_equity": _ratio(total_debt, equity),
        "net_debt_equity": _ratio(
            net_debt,
            equity,
        ),
        "net_debt_ebitda": _ratio(
            net_debt,
            ebitda,
        ),
        "equity_assets": _ratio(equity, assets, 100.0),
        "roe": _ratio(net_income, equity, 100.0),
        "roa": _ratio(net_income, assets, 100.0),
        "market_cap": market_cap,
        "enterprise_value": enterprise_value,
        "shares_outstanding": shares_outstanding,
        "pe": _ratio(market_cap, net_income)
        if net_income is not None and net_income > 0
        else _pick(info, "trailingPE", "pe_ratio"),
        "pb": _ratio(market_cap, equity)
        if equity is not None and equity > 0
        else _pick(info, "priceToBook", "pb"),
        "ev_ebitda": (
            _ratio(market_cap + net_debt, ebitda)
            if market_cap is not None and net_debt is not None and ebitda is not None and ebitda > 0
            else _pick(info, "enterpriseToEbitda", "ev_ebitda")
        ),
        "ev_sales": _ratio(enterprise_value, revenue) if enterprise_value is not None else None,
        "forward_pe": _pick(info, "forwardPE", "forward_pe"),
        "peg": _pick(info, "pegRatio", "trailingPegRatio", "peg"),
        "dividend_yield": (
            lambda value: value * 100.0 if value is not None and 0 <= value <= 1 else value
        )(_pick(info, "dividendYield", "dividend_yield")),
        "fcf_yield": _ratio(fcf, market_cap, 100.0),
        "earnings_yield": _ratio(net_income, market_cap, 100.0),
    }
    periods = set()
    for frame in (balance, income, cashflow):
        if frame is not None:
            periods.update(str(column) for column in frame.columns)
    company_name = prefer_turkish_name(
        *(
            str(info[key])
            for key in ("longName", "shortName", "companyName", "name")
            if info.get(key)
        )
    )
    sector = next(
        (str(info[key]) for key in ("sector", "industry", "sektor") if info.get(key)), None
    )
    currency = next(
        (str(info[key]) for key in ("financialCurrency", "currency") if info.get(key)), None
    )
    flow_period = next(
        (
            dated[key][0][0]
            for key in ("revenue", "net_income", "ebitda")
            if dated[key] and dated[key][0][0] != datetime.min
        ),
        None,
    )
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
        series={key: tuple(series) for key, series in values.items()},
        metadata={
            "balance_period": balance_anchor.isoformat() if balance_anchor else None,
            "flow_period": flow_anchor.isoformat() if flow_anchor else None,
            "historical_publication_verified": "false",
            "period_aggregation": "common_basis"
            if common_purchasing_power
            else "blocked_unverified_basis",
            "industry": info.get("industry"),
            "subsector": info.get("industryKey") or info.get("industryDisp"),
            "description": info.get("longBusinessSummary") or info.get("description"),
            "free_float": info.get("floatShares"),
            "paid_in_capital": info.get("paidInCapital"),
            "exchange": info.get("exchange") or info.get("fullExchangeName") or "BIST",
        },
        flow_period=flow_period,
    )


class BorsapyKapFinancialProvider:
    """Compatibility name: actual source is Is Yatirim via borsapy, not direct KAP."""

    provider_id = "borsapy:isyatirim_statements"

    def __init__(self, archive_root: Path | None = None, *, cache_hours: float = 6):
        from market_intelligence.fundamentals.archive import FinancialArchive

        self.archive = FinancialArchive(archive_root) if archive_root is not None else None
        self.cache_hours = cache_hours

    def _cached(self, canonical: str, as_of: datetime):
        if self.archive is None:
            return None
        cached = self.archive.frames(canonical, self.provider_id, known_at=as_of)
        if cached is None:
            return None
        stamp, digest, frames, info, fast, cumulative = cached
        result = _snapshot_from_frames(
            provider_id=self.provider_id,
            symbol=canonical,
            as_of=as_of,
            **frames,
            info=info,
            fast=fast,
            cumulative_flows=cumulative,
            common_purchasing_power=False,
        )
        return replace(
            result,
            metadata={
                **result.metadata,
                "statement_observed_at": stamp,
                "statement_digest": digest,
                "statement_source": "İş Yatırım / borsapy",
                "archive_status": "cached",
                "historical_publication_verified": "false",
            },
        )

    def fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot:
        try:
            return self._fetch(symbol, as_of=as_of)
        except Exception as exc:
            cached = self._cached(symbol.strip().upper().removesuffix(".IS"), as_of)
            if cached is None:
                raise
            return replace(
                cached,
                errors=(*cached.errors, f"{self.provider_id}:refresh_failed:{type(exc).__name__}"),
                metadata={**cached.metadata, "archive_status": "stale_fallback"},
            )

    def _fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot:
        import borsapy as bp

        canonical = symbol.strip().upper().removesuffix(".IS")
        cached = self._cached(canonical, as_of)
        if (
            cached is not None
            and (
                as_of - datetime.fromisoformat(str(cached.metadata["statement_observed_at"]))
            ).total_seconds()
            < self.cache_hours * 3600
        ):
            return cached
        # Source provides revised tables, not publication-time history. Historical replay
        # must use an observation already known by the requested cutoff.
        if self.archive is not None and as_of < datetime.now(UTC) - timedelta(days=1):
            if cached is not None:
                return cached
            raise ValueError("No archived financial observation known at requested time")
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
        balance = ticker.get_balance_sheet(quarterly=True, financial_group=group, last_n=24)
        income = ticker.get_income_stmt(quarterly=True, financial_group=group, last_n=24)
        try:
            cashflow = ticker.get_cashflow(quarterly=True, financial_group=group, last_n=24)
        except Exception:
            cashflow = None
        observed_at = datetime.now(UTC)
        digest = None
        if self.archive is not None:
            digest = self.archive.put_frames(
                canonical,
                self.provider_id,
                frames={"balance": balance, "income": income, "cashflow": cashflow},
                info=info,
                fast=fast,
                observed_at=observed_at,
                cumulative=True,
            )
        result = _snapshot_from_frames(
            provider_id=self.provider_id,
            symbol=canonical,
            as_of=as_of,
            balance=balance,
            income=income,
            cashflow=cashflow,
            info=info,
            fast=fast,
            cumulative_flows=True,
            common_purchasing_power=False,
        )
        return replace(
            result,
            metadata={
                **result.metadata,
                "statement_observed_at": observed_at.isoformat(),
                "statement_digest": digest,
                "statement_source": "İş Yatırım / borsapy",
                "archive_status": "fresh",
                "historical_publication_verified": "false",
            },
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
            cumulative_flows=False,
            common_purchasing_power=False,
        )


class FinancialProviderChain:
    def __init__(
        self, providers: tuple[FinancialDataProvider, ...], *, quote_provider=None
    ) -> None:
        if not providers:
            raise ValueError("En az bir finansal veri sağlayıcısı gereklidir")
        self.providers = providers
        self.quote_provider = quote_provider

    def fetch(self, symbol: str, *, as_of: datetime) -> FinancialSnapshot | None:
        snapshots: list[FinancialSnapshot] = []
        errors: list[str] = []
        for provider in self.providers:
            try:
                snapshot = provider.fetch(symbol, as_of=as_of)
                snapshots.append(snapshot)
                errors.extend(snapshot.errors)
            except Exception as exc:
                errors.append(f"{provider.provider_id}:{type(exc).__name__}")
        if not snapshots:
            return None
        primary = next((item for item in snapshots if item.coverage > 0), snapshots[0])
        snapshots = [primary, *(item for item in snapshots if item is not primary)]
        metrics = dict(primary.metrics)
        sources = dict(primary.metric_sources)
        providers_used = list(primary.providers_used)
        periods = set(primary.statement_periods)
        for fallback in snapshots[1:]:
            if primary.currency != fallback.currency or primary.currency is None:
                errors.append(f"{fallback.providers_used[0]}:currency_mismatch_or_unknown")
                continue
            primary_end = max(
                (_period(item) or datetime.min for item in primary.statement_periods),
                default=datetime.min,
            )
            fallback_end = max(
                (_period(item) or datetime.min for item in fallback.statement_periods),
                default=datetime.min,
            )
            if primary.metadata.get("inflation_basis", "unverified") != fallback.metadata.get(
                "inflation_basis", "unverified"
            ):
                errors.append(f"{fallback.providers_used[0]}:monetary_basis_mismatch")
                continue
            if primary.flow_period != fallback.flow_period or primary_end != fallback_end:
                errors.append(f"{fallback.providers_used[0]}:statement_period_mismatch")
                continue
            providers_used.extend(fallback.providers_used)
            periods.update(fallback.statement_periods)
            for key, value in fallback.metrics.items():
                if metrics.get(key) is None and value is not None:
                    metrics[key] = value
                    sources[key] = fallback.metric_sources.get(key, fallback.providers_used[0])
        result = replace(
            primary,
            company_name=prefer_turkish_name(
                primary.company_name,
                *(item.company_name for item in snapshots[1:]),
            ),
            sector=primary.sector
            or next((item.sector for item in snapshots[1:] if item.sector), None),
            currency=primary.currency
            or next((item.currency for item in snapshots[1:] if item.currency), None),
            metrics=metrics,
            metric_sources=sources,
            statement_periods=tuple(sorted(periods, reverse=True)),
            providers_used=tuple(dict.fromkeys(providers_used)),
            errors=tuple(dict.fromkeys(errors)),
            series=primary.series,
            metadata=primary.metadata,
            flow_period=primary.flow_period
            or next((item.flow_period for item in snapshots[1:] if item.flow_period), None),
        )

        if self.quote_provider is not None:
            try:
                from market_intelligence.fundamentals.quotes import apply_quote

                result = apply_quote(result, self.quote_provider.fetch(symbol))
            except Exception as exc:
                result = replace(result, errors=(*result.errors, f"quote:{type(exc).__name__}"))
        return result
