"""Auditable valuation primitives used by the research engine.

Adapted from the user's valuation reference library. The module is intentionally
pure and deterministic: it performs valuation math but never invents missing
inputs. Model suitability and data availability are handled separately by
``valuation_policy``.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass


def cost_of_equity_capm(
    rf: float,
    beta: float,
    erp: float,
    country_risk_premium: float = 0.0,
    size_premium: float = 0.0,
) -> float:
    return rf + beta * erp + country_risk_premium + size_premium


def cost_of_debt_after_tax(kd_pretax: float, tax_rate: float) -> float:
    return kd_pretax * (1.0 - tax_rate)


def wacc(equity_value: float, debt_value: float, ke: float, kd_pretax: float, tax_rate: float) -> float:
    total = equity_value + debt_value
    if total <= 0:
        raise ValueError("E + D pozitif olmalı")
    return equity_value / total * ke + debt_value / total * cost_of_debt_after_tax(kd_pretax, tax_rate)


def unlever_beta(levered_beta: float, debt_to_equity: float, tax_rate: float) -> float:
    return levered_beta / (1.0 + (1.0 - tax_rate) * debt_to_equity)


def relever_beta(unlevered_beta: float, debt_to_equity: float, tax_rate: float) -> float:
    return unlevered_beta * (1.0 + (1.0 - tax_rate) * debt_to_equity)


def fisher_real_rate(nominal: float, inflation: float) -> float:
    return (1.0 + nominal) / (1.0 + inflation) - 1.0


def real_growth(nominal_growth: float, inflation: float) -> float:
    return (1.0 + nominal_growth) / (1.0 + inflation) - 1.0


def tms29_index(nominal_amount: float, index_now: float, index_then: float) -> float:
    if index_then == 0:
        raise ValueError("index_then sıfır olamaz")
    return nominal_amount * index_now / index_then


def fcff_from_ebit(ebit: float, tax_rate: float, depreciation: float, capex: float, delta_nwc: float) -> float:
    return ebit * (1.0 - tax_rate) + depreciation - capex - delta_nwc


def fcff_from_net_income(
    net_income: float,
    interest_expense: float,
    tax_rate: float,
    depreciation: float,
    capex: float,
    delta_nwc: float,
) -> float:
    return net_income + interest_expense * (1.0 - tax_rate) + depreciation - capex - delta_nwc


def fcfe_from_fcff(fcff: float, interest_expense: float, tax_rate: float, net_borrowing: float) -> float:
    return fcff - interest_expense * (1.0 - tax_rate) + net_borrowing


def normalize_ebitda(
    history: Sequence[float],
    one_off_items: Sequence[float] | None = None,
    method: str = "median",
) -> float:
    values = list(history)
    if not values:
        raise ValueError("En az bir FAVÖK gözlemi gerekli")
    if one_off_items is not None:
        if len(one_off_items) != len(values):
            raise ValueError("one_off_items uzunluğu history ile aynı olmalı")
        values = [value - one_off for value, one_off in zip(values, one_off_items, strict=True)]
    if method == "median":
        return statistics.median(values)
    if method == "mean":
        return statistics.fmean(values)
    if method == "last":
        return values[-1]
    raise ValueError("method: median | mean | last")


def discount_factor(rate: float, period: float) -> float:
    if rate <= -1:
        raise ValueError("İskonto oranı -100%'den büyük olmalı")
    return 1.0 / ((1.0 + rate) ** period)


def present_value(cash_flow: float, rate: float, period: float) -> float:
    return cash_flow * discount_factor(rate, period)


def npv(rate: float, cash_flows: Sequence[float], mid_year: bool = False) -> float:
    return sum(
        present_value(cash_flow, rate, index - 0.5 if mid_year else float(index))
        for index, cash_flow in enumerate(cash_flows, start=1)
    )


def terminal_value_gordon(last_fcf: float, rate: float, growth: float) -> float:
    if rate <= growth:
        raise ValueError("r > g olmalı")
    return last_fcf * (1.0 + growth) / (rate - growth)


def terminal_value_exit_multiple(metric: float, multiple: float) -> float:
    return metric * multiple


@dataclass(frozen=True)
class DCFInputs:
    fcff: tuple[float, ...]
    wacc: float
    terminal_growth: float | None = None
    exit_multiple: float | None = None
    terminal_metric: float | None = None
    net_debt: float = 0.0
    minority_interest: float = 0.0
    investments_associates: float = 0.0
    non_operating_assets: float = 0.0
    shares_outstanding: float = 1.0
    mid_year: bool = False


@dataclass(frozen=True)
class DCFResult:
    pv_explicit: float
    pv_terminal: float
    enterprise_value: float
    equity_value: float
    value_per_share: float
    terminal_share: float


def run_dcf(inputs: DCFInputs) -> DCFResult:
    if not inputs.fcff:
        raise ValueError("En az bir yıllık FCFF gerekli")
    if inputs.shares_outstanding <= 0:
        raise ValueError("Hisse adedi pozitif olmalı")
    explicit = npv(inputs.wacc, inputs.fcff, inputs.mid_year)
    if inputs.exit_multiple is not None:
        metric = inputs.terminal_metric if inputs.terminal_metric is not None else inputs.fcff[-1]
        terminal = terminal_value_exit_multiple(metric, inputs.exit_multiple)
    elif inputs.terminal_growth is not None:
        terminal = terminal_value_gordon(inputs.fcff[-1], inputs.wacc, inputs.terminal_growth)
    else:
        raise ValueError("terminal_growth veya exit_multiple gerekli")
    n = len(inputs.fcff)
    terminal_period = n - 0.5 if inputs.mid_year else float(n)
    pv_terminal = present_value(terminal, inputs.wacc, terminal_period)
    enterprise = explicit + pv_terminal
    equity = (
        enterprise
        - inputs.net_debt
        - inputs.minority_interest
        + inputs.investments_associates
        + inputs.non_operating_assets
    )
    return DCFResult(
        pv_explicit=explicit,
        pv_terminal=pv_terminal,
        enterprise_value=enterprise,
        equity_value=equity,
        value_per_share=equity / inputs.shares_outstanding,
        terminal_share=pv_terminal / enterprise if enterprise else math.nan,
    )


def sustainable_growth(roe: float, payout_ratio: float) -> float:
    return roe * (1.0 - payout_ratio)


def ddm_gordon(d1: float, rate: float, growth: float) -> float:
    if rate <= growth:
        raise ValueError("r > g olmalı")
    return d1 / (rate - growth)


def ddm_two_stage(d0: float, high_growth: float, years_high: int, stable_growth: float, rate: float) -> float:
    if rate <= stable_growth:
        raise ValueError("r > g_stable olmalı")
    dividend = d0
    value = 0.0
    for year in range(1, years_high + 1):
        dividend *= 1.0 + high_growth
        value += present_value(dividend, rate, year)
    terminal = dividend * (1.0 + stable_growth) / (rate - stable_growth)
    return value + present_value(terminal, rate, years_high)


def ddm_h_model(d0: float, short_growth: float, long_growth: float, half_life: float, rate: float) -> float:
    if rate <= long_growth:
        raise ValueError("r > g_long olmalı")
    return (d0 * (1.0 + long_growth) + d0 * half_life * (short_growth - long_growth)) / (rate - long_growth)


def residual_income_value(
    book_value_0: float,
    roe_forecast: Sequence[float],
    cost_of_equity: float,
    persistence: float = 0.0,
    payout_ratio: float = 0.0,
) -> dict[str, float]:
    book = book_value_0
    pv_residual = 0.0
    last_residual = 0.0
    for year, roe in enumerate(roe_forecast, start=1):
        residual = (roe - cost_of_equity) * book
        pv_residual += present_value(residual, cost_of_equity, year)
        last_residual = residual
        book += roe * book * (1.0 - payout_ratio)
    terminal = 0.0
    if persistence > 0 and roe_forecast:
        denominator = 1.0 + cost_of_equity - persistence
        if denominator <= 0:
            raise ValueError("1 + Ke - persistence pozitif olmalı")
        terminal = present_value(last_residual * persistence / denominator, cost_of_equity, len(roe_forecast))
    value = book_value_0 + pv_residual + terminal
    return {
        "book_value": book_value_0,
        "pv_residual_income": pv_residual,
        "pv_terminal": terminal,
        "value": value,
        "implied_pb": value / book_value_0 if book_value_0 else math.nan,
    }


def epv_greenwald(
    normalized_ebit: float,
    tax_rate: float,
    wacc_rate: float,
    net_debt: float,
    shares: float,
    maintenance_capex_adj: float = 0.0,
) -> dict[str, float]:
    if wacc_rate <= 0:
        raise ValueError("WACC pozitif olmalı")
    if shares <= 0:
        raise ValueError("Hisse adedi pozitif olmalı")
    nopat = normalized_ebit * (1.0 - tax_rate) - maintenance_capex_adj
    enterprise = nopat / wacc_rate
    equity = enterprise - net_debt
    return {
        "nopat": nopat,
        "epv_enterprise": enterprise,
        "epv_equity": equity,
        "epv_per_share": equity / shares,
    }


def implied_price_pe(eps: float, peer_pe: float) -> float:
    return eps * peer_pe


def implied_price_ev_ebitda(ebitda: float, peer_multiple: float, net_debt: float, shares: float) -> float:
    return (peer_multiple * ebitda - net_debt) / shares if shares > 0 else math.nan


def implied_price_pb(book_value_per_share: float, peer_pb: float) -> float:
    return book_value_per_share * peer_pb


def justified_pe_leading(payout_ratio: float, rate: float, growth: float) -> float:
    if rate <= growth:
        raise ValueError("r > g olmalı")
    return payout_ratio / (rate - growth)


def justified_pe_trailing(payout_ratio: float, rate: float, growth: float) -> float:
    if rate <= growth:
        raise ValueError("r > g olmalı")
    return payout_ratio * (1.0 + growth) / (rate - growth)


def justified_pb(roe: float, rate: float, growth: float) -> float:
    if rate <= growth:
        raise ValueError("r > g olmalı")
    return (roe - growth) / (rate - growth)


def peg_ratio(pe: float, growth_pct: float) -> float:
    return math.inf if growth_pct == 0 else pe / growth_pct


@dataclass(frozen=True)
class NAVInputs:
    portfolio_fair_value: float
    cash_and_equivalents: float = 0.0
    receivables: float = 0.0
    other_assets: float = 0.0
    financial_debt: float = 0.0
    other_liabilities: float = 0.0
    minority_interest: float = 0.0
    shares_outstanding: float = 1.0


def nav_per_share(inputs: NAVInputs) -> dict[str, float]:
    if inputs.shares_outstanding <= 0:
        raise ValueError("Hisse adedi pozitif olmalı")
    gross_assets = (
        inputs.portfolio_fair_value
        + inputs.cash_and_equivalents
        + inputs.receivables
        + inputs.other_assets
    )
    liabilities = inputs.financial_debt + inputs.other_liabilities + inputs.minority_interest
    nav = gross_assets - liabilities
    return {
        "gross_assets": gross_assets,
        "total_liabilities": liabilities,
        "nav": nav,
        "nav_per_share": nav / inputs.shares_outstanding,
    }


def nav_premium(price: float, nav_ps: float) -> dict[str, float]:
    if nav_ps == 0:
        return {"pd_nav": math.nan, "premium": math.nan}
    ratio = price / nav_ps
    return {"pd_nav": ratio, "premium": ratio - 1.0}


def sensitivity_grid(
    fn: Callable[[float, float], float],
    x_values: Sequence[float],
    y_values: Sequence[float],
) -> list[list[float]]:
    return [[fn(x, y) for x in x_values] for y in y_values]


def monte_carlo_dcf(
    base: DCFInputs,
    wacc_mu: float,
    wacc_sigma: float,
    growth_mu: float,
    growth_sigma: float,
    fcff_growth_mu: float = 0.0,
    fcff_growth_sigma: float = 0.0,
    n_sims: int = 10_000,
    seed: int = 42,
) -> dict[str, float]:
    rng = random.Random(seed)
    results: list[float] = []
    for _ in range(n_sims):
        trial_wacc = rng.gauss(wacc_mu, wacc_sigma)
        trial_growth = rng.gauss(growth_mu, growth_sigma)
        if trial_wacc <= trial_growth or trial_wacc <= 0:
            continue
        shock = rng.gauss(fcff_growth_mu, fcff_growth_sigma) if fcff_growth_sigma else 0.0
        flows = tuple(cash_flow * ((1.0 + shock) ** (i + 1)) for i, cash_flow in enumerate(base.fcff))
        trial = DCFInputs(
            fcff=flows,
            wacc=trial_wacc,
            terminal_growth=trial_growth,
            net_debt=base.net_debt,
            minority_interest=base.minority_interest,
            investments_associates=base.investments_associates,
            non_operating_assets=base.non_operating_assets,
            shares_outstanding=base.shares_outstanding,
            mid_year=base.mid_year,
        )
        try:
            results.append(run_dcf(trial).value_per_share)
        except ValueError:
            continue
    if not results:
        raise RuntimeError("Geçerli simülasyon üretilemedi")
    results.sort()

    def percentile(p: float) -> float:
        index = min(len(results) - 1, max(0, int(p * len(results))))
        return results[index]

    return {
        "n_valid": float(len(results)),
        "mean": statistics.fmean(results),
        "median": statistics.median(results),
        "stdev": statistics.pstdev(results),
        "p05": percentile(0.05),
        "p25": percentile(0.25),
        "p75": percentile(0.75),
        "p95": percentile(0.95),
        "min": results[0],
        "max": results[-1],
    }


def piotroski_f_score(
    net_income: float,
    total_assets: float,
    total_assets_prev: float,
    cfo: float,
    roa_prev: float,
    lt_debt: float,
    lt_debt_prev: float,
    current_ratio: float,
    current_ratio_prev: float,
    shares: float,
    shares_prev: float,
    gross_margin: float,
    gross_margin_prev: float,
    asset_turnover: float,
    asset_turnover_prev: float,
) -> dict[str, object]:
    roa = net_income / total_assets if total_assets else 0.0
    checks = {
        "roa_positive": roa > 0,
        "cfo_positive": cfo > 0,
        "roa_improved": roa > roa_prev,
        "cfo_above_net_income": cfo > net_income,
        "leverage_fell": (lt_debt / total_assets if total_assets else 0) < (
            lt_debt_prev / total_assets_prev if total_assets_prev else 0
        ),
        "current_ratio_improved": current_ratio > current_ratio_prev,
        "no_dilution": shares <= shares_prev,
        "gross_margin_improved": gross_margin > gross_margin_prev,
        "asset_turnover_improved": asset_turnover > asset_turnover_prev,
    }
    return {"score": sum(bool(value) for value in checks.values()), "detail": checks}


def altman_z_score(
    working_capital: float,
    retained_earnings: float,
    ebit: float,
    market_cap: float,
    total_liabilities: float,
    sales: float,
    total_assets: float,
) -> dict[str, float]:
    if total_assets == 0:
        raise ValueError("total_assets sıfır olamaz")
    x1 = working_capital / total_assets
    x2 = retained_earnings / total_assets
    x3 = ebit / total_assets
    x4 = market_cap / total_liabilities if total_liabilities else 0.0
    x5 = sales / total_assets
    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + x5
    return {"X1": x1, "X2": x2, "X3": x3, "X4": x4, "X5": x5, "Z": z}


def blend_valuations(values: dict[str, float], weights: dict[str, float]) -> dict[str, float]:
    applicable = {name: value for name, value in values.items() if name in weights and weights[name] > 0}
    total_weight = sum(weights[name] for name in applicable)
    if not applicable or total_weight <= 0:
        raise ValueError("Uygulanabilir model/ağırlık yok")
    blended = sum(value * weights[name] for name, value in applicable.items()) / total_weight
    return {
        "blended_value": blended,
        "min": min(applicable.values()),
        "max": max(applicable.values()),
        "dispersion": (max(applicable.values()) - min(applicable.values())) / blended if blended else math.nan,
    }


def margin_of_safety(fair_value: float, market_price: float) -> dict[str, float]:
    if fair_value == 0:
        return {"upside": math.nan, "margin_of_safety": math.nan}
    return {
        "upside": fair_value / market_price - 1.0 if market_price else math.nan,
        "margin_of_safety": (fair_value - market_price) / fair_value,
    }
