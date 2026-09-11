"""Auditable valuation arithmetic; no market access or implicit forecasts.

All rates are fractions, all statement amounts are unscaled currency units, and
share counts are TOTAL shares, never free float. Forecast period 1 covers the
next twelve months; cash flows are discounted at period end. A supplied future
path is an assumption, including one generated from explicit operating drivers.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from market_intelligence.fundamentals.providers import FinancialSnapshot


class ValuationInputError(ValueError):
    """A missing, incompatible or economically invalid model input."""


def _number(value: Any, name: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValuationInputError(f"{name}: boolean cannot be a numeric input")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValuationInputError(f"{name}: a finite number is required") from exc
    if not math.isfinite(number):
        raise ValuationInputError(f"{name}: a finite number is required")
    if minimum is not None and number < minimum:
        raise ValuationInputError(f"{name}: must be >= {minimum}")
    return number


def _positive(value: Any, name: str) -> float:
    number = _number(value, name)
    if number <= 0:
        raise ValuationInputError(f"{name}: must be positive")
    return number


def _fraction(value: Any, name: str) -> float:
    number = _number(value, name, minimum=0)
    if number > 1:
        raise ValuationInputError(f"{name}: use a fraction between 0 and 1")
    return number


def _optional_number(value: Any) -> float | None:
    try:
        return _number(value, "metric")
    except ValuationInputError:
        return None


@dataclass(frozen=True)
class CapitalCost:
    risk_free_rate: float
    beta: float
    equity_risk_premium: float
    country_risk_premium: float
    pre_tax_cost_of_debt: float
    tax_rate: float
    equity_weight: float
    debt_weight: float

    def calculate(self) -> dict[str, float]:
        risk_free = _number(self.risk_free_rate, "risk_free_rate")
        beta = _number(self.beta, "beta")
        premium = _number(self.equity_risk_premium, "equity_risk_premium", minimum=0)
        country = _number(self.country_risk_premium, "country_risk_premium", minimum=0)
        debt_cost = _number(self.pre_tax_cost_of_debt, "pre_tax_cost_of_debt", minimum=0)
        tax = _fraction(self.tax_rate, "tax_rate")
        equity_weight = _fraction(self.equity_weight, "equity_weight")
        debt_weight = _fraction(self.debt_weight, "debt_weight")
        if not math.isclose(equity_weight + debt_weight, 1.0, abs_tol=1e-9):
            raise ValuationInputError("equity_weight + debt_weight must equal 1")
        equity_cost = risk_free + beta * premium + country
        after_tax_debt_cost = debt_cost * (1 - tax)
        wacc = _positive(equity_weight * equity_cost + debt_weight * after_tax_debt_cost, "wacc")
        return {
            "cost_of_equity": equity_cost,
            "after_tax_cost_of_debt": after_tax_debt_cost,
            "wacc": wacc,
        }


def fcff(
    *,
    ebit: float,
    tax_rate: float,
    depreciation_amortization: float,
    capex: float,
    delta_operating_nwc: float,
) -> dict[str, float]:
    """Standard model NOPAT = EBIT*(1-T); CapEx is a positive cash outflow.

    The tax rate is explicit and is a model assumption, not reported cash tax. With
    negative EBIT this formula models a tax benefit; callers must supply a zero rate
    where no loss-related tax benefit is expected to be usable in that period.
    """
    operating_profit = _number(ebit, "ebit")
    tax = _fraction(tax_rate, "tax_rate")
    depreciation = _number(depreciation_amortization, "depreciation_amortization", minimum=0)
    investment = _number(capex, "capex", minimum=0)
    nwc_change = _number(delta_operating_nwc, "delta_operating_nwc")
    nopat = operating_profit * (1 - tax)
    result = nopat + depreciation - investment - nwc_change
    return {"nopat": _number(nopat, "nopat"), "fcff": _number(result, "fcff")}


@dataclass(frozen=True)
class ForecastYear:
    period: int
    ebit: float
    depreciation_amortization: float
    capex: float
    delta_operating_nwc: float
    tax_rate: float

    def calculate(self) -> dict[str, float | int]:
        if isinstance(self.period, bool) or not isinstance(self.period, int) or self.period < 1:
            raise ValuationInputError("forecast period must be a positive integer")
        return {
            **asdict(self),
            **fcff(
                ebit=self.ebit,
                tax_rate=self.tax_rate,
                depreciation_amortization=self.depreciation_amortization,
                capex=self.capex,
                delta_operating_nwc=self.delta_operating_nwc,
            ),
        }


def forecast_from_drivers(
    *,
    base_revenue: float,
    base_operating_nwc: float,
    drivers: Sequence[Mapping[str, Any]],
) -> tuple[ForecastYear, ...]:
    """Calculate a forecast only from an explicitly supplied annual driver path.

    Driver rows require revenue_growth, ebit_margin, depreciation_ratio,
    capex_ratio, operating_nwc_ratio and tax_rate. NWC means noncash operating
    current assets less nondebt operating current liabilities. It is not a raw
    current-assets minus current-liabilities shortcut.
    """
    revenue = _positive(base_revenue, "base_revenue")
    previous_nwc = _number(base_operating_nwc, "base_operating_nwc")
    forecasts = []
    if not drivers:
        raise ValuationInputError("at least one forecast driver row is required")
    for period, row in enumerate(drivers, 1):
        growth = _number(row.get("revenue_growth"), "revenue_growth")
        if growth <= -1:
            raise ValuationInputError("revenue_growth must be greater than -1")
        revenue = _positive(revenue * (1 + growth), "forecast_revenue")
        margin = _number(row.get("ebit_margin"), "ebit_margin")
        depreciation_ratio = _fraction(row.get("depreciation_ratio"), "depreciation_ratio")
        capex_ratio = _fraction(row.get("capex_ratio"), "capex_ratio")
        nwc_ratio = _number(row.get("operating_nwc_ratio"), "operating_nwc_ratio")
        tax = _fraction(row.get("tax_rate"), "tax_rate")
        nwc = revenue * nwc_ratio
        forecasts.append(
            ForecastYear(
                period=period,
                ebit=revenue * margin,
                depreciation_amortization=revenue * depreciation_ratio,
                capex=revenue * capex_ratio,
                delta_operating_nwc=nwc - previous_nwc,
                tax_rate=tax,
            )
        )
        previous_nwc = nwc
    return tuple(forecasts)


def discounted_cash_flow(
    forecasts: Sequence[ForecastYear],
    *,
    wacc: float,
    terminal_growth: float,
    net_debt: float,
    total_diluted_shares: float,
    equity_bridge_adjustment: float,
) -> dict[str, Any]:
    """FCFF/WACC with a Gordon terminal value and an explicit equity bridge.

    Equity bridge adjustment adds nonoperating assets and subtracts minority /
    preferred claims not already in net debt. Zero must be supplied explicitly when
    none apply. A negative equity value is reported; it is not clipped to zero.
    """
    rate = _positive(wacc, "wacc")
    growth = _number(terminal_growth, "terminal_growth")
    debt = _number(net_debt, "net_debt")
    shares = _positive(total_diluted_shares, "total_diluted_shares")
    adjustment = _number(equity_bridge_adjustment, "equity_bridge_adjustment")
    if growth <= -1:
        raise ValuationInputError("terminal_growth must be greater than -1")
    if rate <= growth:
        raise ValuationInputError("WACC must exceed terminal growth")
    if not forecasts:
        raise ValuationInputError("at least one explicit forecast is required")
    rows = []
    for expected_period, forecast in enumerate(forecasts, 1):
        row = forecast.calculate()
        if row["period"] != expected_period:
            raise ValuationInputError("forecast periods must be contiguous starting at 1")
        try:
            discount_factor = (1 + rate) ** expected_period
        except OverflowError as exc:
            raise ValuationInputError("forecast discount factor overflows") from exc
        row["present_value"] = _number(row["fcff"] / discount_factor, "present_value")
        rows.append(row)
    if rows[-1]["fcff"] <= 0:
        raise ValuationInputError("Gordon terminal value requires a positive normalized final FCFF")
    terminal_value = _number(rows[-1]["fcff"] * (1 + growth) / (rate - growth), "terminal_value")
    terminal_pv = terminal_value / (1 + rate) ** len(rows)
    cashflow_pv = sum(row["present_value"] for row in rows)
    enterprise_value = _number(cashflow_pv + terminal_pv, "enterprise_value")
    equity_value = _number(enterprise_value - debt + adjustment, "equity_value")
    warnings = []
    terminal_share = terminal_pv / enterprise_value if enterprise_value > 0 else None
    if terminal_share is not None and terminal_share > 0.75:
        warnings.append("Firma değerinin %75'inden fazlası terminal değerden geliyor.")
    if equity_value < 0:
        warnings.append("Özsermaye değeri negatif; sonuç pozitif hisse hedefi olarak yorumlanamaz.")
    if any(row["ebit"] < 0 and row["tax_rate"] > 0 for row in rows):
        warnings.append(
            "Zarar dönemlerinde vergi faydası varsayılmıştır; kullanılabilirliği doğrulanmalıdır."
        )
    return {
        "status": "AVAILABLE",
        "wacc": rate,
        "terminal_growth": growth,
        "forecast_cashflows": rows,
        "cashflow_present_value": cashflow_pv,
        "terminal_value": terminal_value,
        "terminal_present_value": terminal_pv,
        "terminal_value_share": terminal_share,
        "enterprise_value": enterprise_value,
        "net_debt": debt,
        "equity_bridge_adjustment": adjustment,
        "equity_value": equity_value,
        "total_diluted_shares": shares,
        "value_per_share": equity_value / shares,
        "warnings": warnings,
    }


def dcf_sensitivity(
    forecasts: Sequence[ForecastYear],
    *,
    wacc_rates: Sequence[float],
    terminal_growth_rates: Sequence[float],
    net_debt: float,
    total_diluted_shares: float,
    equity_bridge_adjustment: float,
) -> list[dict[str, Any]]:
    rows = []
    for rate in wacc_rates:
        for growth in terminal_growth_rates:
            try:
                value = discounted_cash_flow(
                    forecasts,
                    wacc=rate,
                    terminal_growth=growth,
                    net_debt=net_debt,
                    total_diluted_shares=total_diluted_shares,
                    equity_bridge_adjustment=equity_bridge_adjustment,
                )["value_per_share"]
                error = None
            except ValuationInputError as exc:
                value, error = None, str(exc)
            rows.append(
                {"wacc": rate, "terminal_growth": growth, "value_per_share": value, "error": error}
            )
    return rows


def sector_suitability(sector: str | None) -> dict[str, Any]:
    normalized = (sector or "").casefold().translate(str.maketrans("çğıöşü", "cgiosu"))
    if any(word in normalized for word in ("bank", "insurance", "sigorta", "financial", "finans")):
        return {
            "category": "financial",
            "fcff_suitable": False,
            "preferred_methods": ["P/B with ROE and asset quality", "residual_income", "DDM"],
        }
    if any(word in normalized for word in ("gyo", "reit", "real estate", "gayrimenkul")):
        return {
            "category": "real_estate",
            "fcff_suitable": False,
            "preferred_methods": ["NAV using current property appraisals"],
        }
    if "holding" in normalized or "conglomerate" in normalized:
        return {
            "category": "holding",
            "fcff_suitable": False,
            "preferred_methods": ["SOTP using ownership-adjusted subsidiary values"],
        }
    return {
        "category": "operating_company" if normalized else "unknown",
        "fcff_suitable": bool(normalized),
        "preferred_methods": ["FCFF/WACC", "peer_multiples"] if normalized else [],
    }


def _metric(snapshot: FinancialSnapshot, *keys: str) -> float | None:
    for key in keys:
        value = _optional_number(snapshot.metrics.get(key))
        if value is not None:
            return value
    return None


def _market_inputs(
    snapshot: FinancialSnapshot,
    current_price: float | None,
    price_currency: str | None,
) -> tuple[dict[str, Any], list[str]]:
    warnings = []
    shares = _metric(snapshot, "shares_outstanding")
    # Free float and paid-in capital are deliberately not share-count fallbacks.
    shares = shares if shares is not None and shares > 0 else None
    price = _optional_number(current_price)
    if current_price is not None and (price is None or price <= 0):
        warnings.append("Geçerli pozitif güncel fiyat yok; fiyat bazlı çarpanlar hesaplanmadı.")
        price = None
    financial_currency = (snapshot.currency or "").upper()
    quote_currency = (price_currency or "").upper()
    compatible = not current_price or bool(
        financial_currency and quote_currency and financial_currency == quote_currency
    )
    if current_price is not None and not compatible:
        warnings.append("Fiyat ve finansal tablo para birimi eşleşmedi veya doğrulanamadı.")
    if current_price is not None:
        market_cap = price * shares if price and shares and compatible else None
        market_cap_basis = "current_price * total_shares_outstanding"
    else:
        market_cap = _metric(snapshot, "market_cap")
        market_cap = market_cap if market_cap is not None and market_cap > 0 else None
        market_cap_basis = "provider_market_cap"
    net_debt = _metric(snapshot, "net_debt")
    if net_debt is None:
        debt, cash = _metric(snapshot, "total_debt"), _metric(snapshot, "cash")
        if debt is not None and cash is not None:
            net_debt = debt - cash
    # This is explicitly the simplified bridge, not a vendor enterprise-value fact.
    ev = market_cap + net_debt if market_cap is not None and net_debt is not None else None
    values = {
        "price": price,
        "total_shares_outstanding": shares,
        "market_cap": market_cap,
        "market_cap_basis": market_cap_basis,
        "net_debt": net_debt,
        "enterprise_value_simplified": ev,
        "enterprise_value_formula": "market_cap + financial_debt - cash",
        "enterprise_value_limitations": "Minority/preferred claims and nonoperating investments are excluded unless included in input net debt.",
        "financial_currency": snapshot.currency,
        "price_currency": price_currency,
    }
    return values, warnings


def _market_multiples(snapshot: FinancialSnapshot, inputs: Mapping[str, Any]) -> dict[str, Any]:
    cap, ev = inputs["market_cap"], inputs["enterprise_value_simplified"]
    definitions = {
        "pe": (cap, _metric(snapshot, "net_income_ttm"), "market_cap / net_income_ttm"),
        "pb": (cap, _metric(snapshot, "equity"), "market_cap / equity"),
        "price_sales": (cap, _metric(snapshot, "revenue_ttm"), "market_cap / revenue_ttm"),
        "ev_ebitda": (
            ev,
            _metric(snapshot, "ebitda_ttm"),
            "simplified_enterprise_value / ebitda_ttm",
        ),
        "ev_sales": (
            ev,
            _metric(snapshot, "revenue_ttm"),
            "simplified_enterprise_value / revenue_ttm",
        ),
    }
    result = {}
    for key, (numerator, denominator, formula) in definitions.items():
        valid = (
            numerator is not None and numerator > 0 and denominator is not None and denominator > 0
        )
        result[key] = {
            "value": numerator / denominator if valid else None,
            "formula": formula,
            "status": "AVAILABLE" if valid else "UNAVAILABLE",
            "reason": None if valid else "Pozitif ve eksiksiz pay/payda gerekli.",
            "basis": "reported_TTM" if key != "pb" else "latest_book_equity",
        }
    cfo, capex = _metric(snapshot, "cfo_ttm"), _metric(snapshot, "capex_ttm")
    cashflow = cfo - abs(capex) if cfo is not None and capex is not None else None
    valid = cap is not None and cap > 0 and cashflow is not None
    result["fcf_yield"] = {
        "value": cashflow / cap * 100 if valid else None,
        "formula": "(cfo_ttm - abs(capex_ttm)) / market_cap * 100",
        "status": "AVAILABLE" if valid else "UNAVAILABLE",
        "reason": None if valid else "CFO, CapEx ve pozitif piyasa değeri gerekli.",
        "basis": "CFO_less_capex_proxy_percent; not FCFF or a DCF value",
    }
    return result


def _validate_basis(assumptions: Mapping[str, Any], snapshot: FinancialSnapshot) -> None:
    if assumptions.get("example_only"):
        raise ValuationInputError("example_only configuration cannot value a real company")
    source = assumptions.get("assumption_source")
    if not isinstance(source, str) or not source.strip():
        raise ValuationInputError(
            "assumption_source must explain who supplied the estimates and when"
        )
    currencies = [assumptions.get(key) for key in ("currency", "discount_currency")]
    if not snapshot.currency or any(
        not isinstance(value, str) or value.upper() != snapshot.currency.upper()
        for value in currencies
    ):
        raise ValuationInputError("cash-flow, discount-rate and statement currencies must match")
    bases = [
        assumptions.get(key)
        for key in ("cashflow_basis", "discount_rate_basis", "terminal_growth_basis")
    ]
    if bases[0] not in ("nominal", "real") or len(set(bases)) != 1:
        raise ValuationInputError(
            "cash-flow, discount-rate and terminal-growth bases must all be nominal or all real"
        )
    if bases[0] == "real" and not assumptions.get("real_base_date"):
        raise ValuationInputError(
            "real_base_date is required for constant purchasing-power forecasts"
        )
    if assumptions.get("amount_unit") != "currency_units":
        raise ValuationInputError(
            "amount_unit must be currency_units; normalize thousands/millions first"
        )


def build_valuation_analysis(
    snapshot: FinancialSnapshot | None,
    *,
    current_price: float | None = None,
    price_currency: str | None = None,
    assumptions: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """JSON-ready report integration. Missing assumptions never fabricate a target.

    The caller owns fetching data, persisting assumptions and choosing quote time.
    No I/O, sector score changes, or trading decisions occur in this helper.
    """
    required = [
        "assumption_source",
        "currency",
        "discount_currency",
        "cashflow_basis",
        "discount_rate_basis",
        "terminal_growth_basis",
        "amount_unit",
        "capital_cost",
        "terminal_growth",
        "equity_bridge_adjustment",
        "total_diluted_shares",
        "forecasts or forecast_drivers",
    ]
    if snapshot is None:
        return {
            "market_multiples": {},
            "historical": {},
            "sector": sector_suitability(None),
            "dcf": {
                "status": "UNAVAILABLE",
                "missing_inputs": ["financial_snapshot"],
                "value_per_share": None,
            },
            "warnings": ["Finansal veri yok."],
        }
    inputs, warnings = _market_inputs(snapshot, current_price, price_currency)
    suitability = sector_suitability(snapshot.sector)
    if suitability["category"] == "unknown":
        warnings.append("Sektör doğrulanmadan otomatik FCFF değerlemesi yapılmaz.")
    historical = {
        key: _metric(snapshot, key)
        for key in (
            "revenue_ttm",
            "cfo_ttm",
            "capex_ttm",
            "depreciation_amortization_ttm",
            "operating_nwc",
            "delta_operating_nwc_ttm",
        )
    }
    historical["depreciation_amortization_ttm"] = _metric(
        snapshot, "depreciation_amortization_ttm", "depreciation_ttm"
    )
    historical["operating_nwc"] = _metric(snapshot, "operating_nwc", "working_capital")
    historical["ebit_ttm"] = _metric(snapshot, "ebit_ttm", "operating_profit_ttm")
    if historical["cfo_ttm"] is not None and historical["capex_ttm"] is not None:
        historical["cfo_less_capex"] = historical["cfo_ttm"] - abs(historical["capex_ttm"])
    else:
        historical["cfo_less_capex"] = None
    result: dict[str, Any] = {
        "inputs": inputs,
        "input_sources": dict(snapshot.metric_sources),
        "statement_periods": list(snapshot.statement_periods),
        "as_of": snapshot.as_of.isoformat(),
        "sector": suitability,
        "market_multiples": _market_multiples(snapshot, inputs),
        "historical": historical,
        "warnings": warnings,
        "dcf": {
            "status": "ASSUMPTIONS_REQUIRED",
            "missing_inputs": required,
            "value_per_share": None,
        },
    }
    if not suitability["fcff_suitable"]:
        result["dcf"] = {
            "status": "NOT_APPLICABLE",
            "value_per_share": None,
            "reason": "Sektör için özel model veya sektör doğrulaması gerekli.",
            "preferred_methods": suitability["preferred_methods"],
        }
        return result
    if assumptions is None:
        return result
    try:
        _validate_basis(assumptions, snapshot)
        capital_payload = assumptions.get("capital_cost")
        if not isinstance(capital_payload, Mapping):
            raise ValuationInputError("capital_cost mapping is required")
        capital = CapitalCost(**capital_payload)
        capital_values = capital.calculate()
        if bool(assumptions.get("forecasts")) == bool(assumptions.get("forecast_drivers")):
            raise ValuationInputError("supply exactly one of forecasts or forecast_drivers")
        if assumptions.get("forecast_drivers"):
            forecasts = forecast_from_drivers(
                base_revenue=historical["revenue_ttm"],
                base_operating_nwc=historical["operating_nwc"],
                drivers=assumptions["forecast_drivers"],
            )
        else:
            forecasts = tuple(ForecastYear(**row) for row in assumptions["forecasts"])
        shares = assumptions.get("total_diluted_shares")
        if shares is None:
            shares = _metric(snapshot, "diluted_shares_outstanding")
        common = {
            "net_debt": inputs["net_debt"],
            "total_diluted_shares": shares,
            "equity_bridge_adjustment": assumptions.get("equity_bridge_adjustment"),
        }
        growth = _number(assumptions.get("terminal_growth"), "terminal_growth")
        dcf = discounted_cash_flow(
            forecasts, wacc=capital_values["wacc"], terminal_growth=growth, **common
        )
        # These are mechanical stress scenarios, explicitly labelled in output.
        step = _positive(assumptions.get("sensitivity_step", 0.01), "sensitivity_step")
        rates = [capital_values["wacc"] + change * step for change in (-1, 0, 1)]
        growths = [growth + change * step for change in (-1, 0, 1)]
        dcf.update(
            {
                "capital_cost": capital_values,
                "assumption_source": assumptions["assumption_source"],
                "assumptions": dict(assumptions),
                "currency": snapshot.currency,
                "sensitivity": dcf_sensitivity(
                    forecasts, wacc_rates=rates, terminal_growth_rates=growths, **common
                ),
                "sensitivity_basis": {"kind": "mechanical_stress_scenarios", "step": step},
                "cashflow_timing": "end_of_year; period_1_is_next_12_months",
                "missing_inputs": [],
            }
        )
        price = inputs["price"]
        dcf["upside_percent"] = (
            (dcf["value_per_share"] / price - 1) * 100
            if price and price_currency and price_currency.upper() == snapshot.currency.upper()
            else None
        )
        result["dcf"] = dcf
        if all(
            historical[key] is not None
            for key in (
                "ebit_ttm",
                "depreciation_amortization_ttm",
                "capex_ttm",
                "delta_operating_nwc_ttm",
            )
        ):
            historical["modeled_fcff_ttm"] = {
                **fcff(
                    ebit=historical["ebit_ttm"],
                    tax_rate=capital.tax_rate,
                    depreciation_amortization=historical["depreciation_amortization_ttm"],
                    capex=abs(historical["capex_ttm"]),
                    delta_operating_nwc=historical["delta_operating_nwc_ttm"],
                ),
                "basis": "historical_flows_with_assumed_tax_rate",
                "tax_rate": capital.tax_rate,
            }
    except (ValuationInputError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        result["dcf"] = {
            "status": "INVALID_INPUTS",
            "value_per_share": None,
            "errors": [str(exc)],
            "missing_inputs": [],
        }
    return result
