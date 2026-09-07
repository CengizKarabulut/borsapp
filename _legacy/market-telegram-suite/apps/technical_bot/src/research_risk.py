"""Auditable risk and final scoring layer for the integrated research command.

Missing evidence is never converted into a neutral-looking risk score. Company
quality excludes valuation so the independent valuation dimension is not counted
twice. Advanced valuation policy is attached after the core data pass so model
suitability can use both peer context and financial evidence without fabricating
intrinsic-value assumptions.
"""

from __future__ import annotations

from dataclasses import replace

from src import research_engine as core
from src.research_contracts import (
    enrich_beneish,
    sanitize_profile_financials,
    sanitize_valuation,
)
from src.research_engine import LevelZone, ResearchDimension, RiskItem
from src.research_extensions import enrich_financial_analysis, enrich_valuation
from src.research_technical import _technical_analysis
from src.valuation_policy import build_valuation_policy

MIN_DIMENSION_COVERAGE = 0.50


def _risk_engine(
    profile: str,
    financial: dict,
    valuation: dict,
    technical: dict,
    supports: tuple[LevelZone, ...],
) -> tuple[RiskItem | None, tuple[RiskItem, ...]]:
    fm = financial.get("metrics", {})
    risks: list[RiskItem] = []

    if profile == "BANK":
        capital_proxy = core._finite(fm.get("equity_assets"))
        loan_deposit = core._finite(fm.get("loans_deposits"))
        bank_score, bank_coverage = core._weighted(
            [
                (core._score_higher(capital_proxy, 5.0, 14.0), 1.0),
                (
                    core._score_lower(abs(loan_deposit - 0.9), 0.0, 0.5)
                    if loan_deposit is not None
                    else None,
                    1.0,
                ),
            ]
        )
        if bank_score is not None and bank_coverage > 0:
            risks.append(
                RiskItem(
                    "Banka bilanço riski",
                    round(100.0 - bank_score, 1),
                    "Resmi SYR/NPL yoksa özkaynak/aktif ve kredi/mevduat yalnız vekil göstergedir.",
                )
            )
    else:
        nde = core._finite(fm.get("net_debt_equity"))
        nd_ebitda = core._finite(fm.get("net_debt_ebitda"))
        current_ratio = core._finite(fm.get("current_ratio"))
        leverage_score, leverage_coverage = core._weighted(
            [
                (core._score_lower(nde, 0.0, 2.0), 1.0),
                (core._score_lower(nd_ebitda, 0.0, 4.0), 1.2),
                (core._score_target(current_ratio, 1.2, 2.8, 0.5, 6.0), 0.8),
            ]
        )
        if leverage_score is not None and leverage_coverage > 0:
            risks.append(
                RiskItem(
                    "Finansal kaldıraç",
                    round(100.0 - leverage_score, 1),
                    f"Net borç yönü: {financial.get('debt_direction', '—')}; "
                    f"net borç/FAVÖK {nd_ebitda if nd_ebitda is not None else '—'}.",
                )
            )

    quality_score = core._finite(financial.get("earnings_quality_score"))
    quality_coverage = core._finite(financial.get("earnings_quality_coverage")) or 0.0
    if quality_score is not None and quality_coverage >= 0.35:
        if profile == "BANK":
            quality_evidence = (
                f"Net faiz büyümesi {fm.get('net_interest_growth', '—')} · "
                f"ROE {fm.get('roe', '—')} · gider büyümesi {fm.get('operating_expense_growth', '—')}."
            )
        else:
            quality_evidence = (
                f"CFO/net kâr {fm.get('cfo_net_income', '—')} · "
                f"accrual %{fm.get('accrual_ratio', '—')}."
            )
        risks.append(RiskItem("Kâr kalitesi", round(100.0 - quality_score, 1), quality_evidence))

    valuation_score = core._finite(valuation.get("score"))
    valuation_coverage = core._finite(valuation.get("coverage")) or 0.0
    if valuation_score is not None and valuation_coverage >= 0.35:
        risks.append(
            RiskItem(
                "Değerleme hassasiyeti",
                round(100.0 - valuation_score, 1),
                f"Birincil yöntem: {valuation.get('primary_model', '—')} · "
                f"akran kapsamı: {valuation.get('scope', '—')} · "
                f"model güveni %{round(float(valuation.get('model_confidence') or 0.0) * 100)}.",
            )
        )

    technical_score = core._finite(technical.get("score"))
    atr_pct = core._finite(technical.get("atr_pct"))
    if technical_score is not None:
        support_penalty = 15.0 if not supports else min(float(supports[0].distance_atr) * 4.0, 20.0)
        technical_risk = 100.0 - technical_score
        technical_risk = min(
            100.0,
            technical_risk + support_penalty + (10.0 if atr_pct is not None and atr_pct > 5 else 0.0),
        )
        divergence = technical.get("latest_rsi_divergence")
        if divergence and "Bearish" in str(divergence.get("kind")):
            technical_risk = min(100.0, technical_risk + 8.0)
        hierarchy = technical.get("structure_hierarchy") or {}
        structure = technical.get("structure", {})
        elliott = technical.get("elliott", {})
        evidence = f"Yapı {structure.get('state', '—')} / {structure.get('event', '—')}"
        if hierarchy.get("summary"):
            evidence += f" · Hiyerarşi {hierarchy.get('summary')}"
        if atr_pct is not None:
            evidence += f" · ATR %{atr_pct:.1f}"
        evidence += (
            f" · AlphaTrend {technical.get('alpha_trend_state', '—')}"
            f" · RSI uyumsuzluk {divergence.get('kind') if divergence else 'yok'}"
            f" · Elliott {elliott.get('primary', '—')}"
        )
        risks.append(RiskItem("Teknik yapı", round(technical_risk, 1), evidence))

    turnover = core._finite(technical.get("average_turnover_20"))
    if turnover is not None:
        if turnover < 25_000_000:
            liquidity_risk = 85.0
        elif turnover < 100_000_000:
            liquidity_risk = 55.0
        else:
            liquidity_risk = 20.0
        risks.append(RiskItem("Likidite", liquidity_risk, f"20 günlük ortalama TL hacim {turnover:,.0f}."))

    ordered = tuple(sorted(risks, key=lambda item: item.score, reverse=True))
    main_risk = ordered[0] if ordered and ordered[0].score >= 35.0 else None
    return main_risk, ordered


def _quality_dimension(report) -> ResearchDimension:
    factors = [
        factor
        for factor in report.fundamental.factors
        if "değerleme" not in factor.name.casefold() and "degerleme" not in factor.name.casefold()
    ]
    available = [factor for factor in factors if factor.score is not None]
    if not available:
        return ResearchDimension(
            "Şirket Kalitesi",
            None,
            0.0,
            "VERİ YETERSİZ",
            "Değerleme hariç şirket kalite faktörlerinde yeterli veri yok.",
        )
    used_weight = sum(max(float(factor.coverage), 0.01) for factor in available)
    score = sum(
        float(factor.score) / 5.0 * 100.0 * max(float(factor.coverage), 0.01)
        for factor in available
    ) / used_weight
    coverage = sum(float(factor.coverage) for factor in factors) / max(len(factors), 1)
    return ResearchDimension(
        "Şirket Kalitesi",
        round(score, 1),
        round(coverage, 2),
        core._label(score, "GÜÇLÜ", "ORTA", "ZAYIF"),
        "Değerleme hariç sektör uyarlamalı kârlılık, büyüme, bilanço/sermaye ve nakit faktörleri.",
    )


def _coverage_gate_dimension(dimension: ResearchDimension) -> ResearchDimension:
    coverage = max(0.0, min(1.0, float(dimension.coverage)))
    if dimension.score is None or coverage >= MIN_DIMENSION_COVERAGE:
        return replace(dimension, coverage=round(coverage, 2))
    return replace(
        dimension,
        score=None,
        coverage=round(coverage, 2),
        label="VERİ YETERSİZ",
        summary=(
            f"{dimension.summary} Kapsam %{round(coverage * 100)}; "
            "bu boyut genel araştırma skoruna katılmadı."
        ),
    )


def _valuation_dimension(valuation: dict) -> ResearchDimension:
    score = core._finite(valuation.get("score"))
    coverage = core._finite(valuation.get("coverage")) or 0.0
    return ResearchDimension(
        "Değerleme",
        score,
        coverage,
        core._label(score, "İSKONTOLU / GÜÇLÜ", "MAKUL", "PRİMLİ / ZAYIF"),
        f"Birincil yöntem {valuation.get('primary_model', '—')}; model uygunluğu ayrı raporlanır. "
        f"Göreli karşılaştırma: {valuation.get('scope', '—')}.",
    )


def _finalize_dimensions(report):
    dimensions = list(report.dimensions)
    if dimensions:
        dimensions[0] = _quality_dimension(report)
    dimensions = [_coverage_gate_dimension(dimension) for dimension in dimensions]

    available = [dimension for dimension in dimensions if dimension.score is not None]
    if available:
        used_weight = sum(max(float(dimension.coverage), 0.01) for dimension in available)
        research_score = sum(
            float(dimension.score) * max(float(dimension.coverage), 0.01)
            for dimension in available
        ) / used_weight
    else:
        research_score = None
    coverage = sum(float(dimension.coverage) for dimension in dimensions) / max(len(dimensions), 1)
    return replace(
        report,
        dimensions=tuple(dimensions),
        research_score=None if research_score is None else round(research_score, 1),
        coverage=round(coverage, 2),
    )


def build_research_report(symbol: str):
    """Build the production report with one statement fetch and raw-first extensions."""
    previous_risk = core._risk_engine
    previous_technical = core._technical_analysis
    previous_financial = core._financial_analysis
    previous_peer = core._peer_valuation
    state: dict[str, dict] = {}

    def financial_wrapper(fundamental, balance, income, cashflow):
        base = previous_financial(fundamental, balance, income, cashflow)
        financial = enrich_financial_analysis(base, fundamental, balance, income, cashflow)
        financial = enrich_beneish(financial, fundamental, balance, income, cashflow)
        financial = sanitize_profile_financials(financial, fundamental.profile)
        state["financial"] = financial
        return financial

    def peer_wrapper(ticker: str, profile: str):
        base = previous_peer(ticker, profile)
        financial = state.get("financial")
        if financial is None:
            return sanitize_valuation(base)
        return sanitize_valuation(enrich_valuation(base, financial, symbol=ticker, profile=profile))

    core._risk_engine = _risk_engine
    core._technical_analysis = _technical_analysis
    core._financial_analysis = financial_wrapper
    core._peer_valuation = peer_wrapper
    try:
        report = core.build_research_report(symbol)
    finally:
        core._risk_engine = previous_risk
        core._technical_analysis = previous_technical
        core._financial_analysis = previous_financial
        core._peer_valuation = previous_peer

    combined_metrics = dict(report.fundamental.metrics)
    combined_metrics.update(report.financial.get("metrics") or {})
    valuation = build_valuation_policy(
        report.profile,
        report.sector,
        combined_metrics,
        report.valuation,
        report.price,
    )
    valuation = sanitize_valuation(valuation)
    dimensions = tuple(
        _valuation_dimension(valuation) if dimension.name == "Değerleme" else dimension
        for dimension in report.dimensions
    )
    main_risk, risks = _risk_engine(report.profile, report.financial, valuation, report.technical, report.supports)
    report = replace(
        report,
        valuation=valuation,
        dimensions=dimensions,
        main_risk=main_risk,
        risks=risks,
        note=(
            report.note
            + " Model uygunluğu şirket tipine göre değerlendirilir; eksik NAD/WACC/Ke gibi girdiler yerine varsayım uydurulmaz."
        ),
    )
    return _finalize_dimensions(report)
