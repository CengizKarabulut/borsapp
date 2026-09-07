"""Post-processing contracts for the integrated research pipeline.

This module is deliberately policy-narrow. It completes forensic diagnostics and
removes economically invalid presentation sentinels without changing the raw-first
valuation source policy. In particular, raw earnings/FCF yields are never replaced
with reciprocals of provider fallback multiples.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from src import research_engine as core
from src import research_extensions as ext
from src.fundamental_analysis import FundamentalReport

VALUATION_MULTIPLES = ("pe", "pb", "ev_ebitda", "ev_sales", "ps", "p_fcf", "peg")
PEER_MULTIPLES = ("pe", "pb", "ev_ebitda", "ev_sales")
GYO_NON_COMPARABLE_MARGIN_LIMIT = 500.0


def _beneish(
    *,
    revenue: float | None,
    revenue_prev: float | None,
    receivables: float | None,
    receivables_prev: float | None,
    gross_profit: float | None,
    gross_profit_prev: float | None,
    current_assets: float | None,
    current_assets_prev: float | None,
    ppe: float | None,
    ppe_prev: float | None,
    assets: float | None,
    assets_prev: float | None,
    depreciation: float | None,
    depreciation_prev: float | None,
    sga: float | None,
    sga_prev: float | None,
    liabilities: float | None,
    liabilities_prev: float | None,
    net_income: float | None,
    cfo: float | None,
) -> dict[str, Any]:
    """Calculate the classic eight-component Beneish M-score only on full evidence."""

    def div(a: float | None, b: float | None) -> float | None:
        return ext._ratio(a, b)

    dsri = div(div(receivables, revenue), div(receivables_prev, revenue_prev))
    gross_margin = None if revenue is None or gross_profit is None else gross_profit / revenue
    gross_margin_prev = (
        None if revenue_prev is None or gross_profit_prev is None else gross_profit_prev / revenue_prev
    )
    gmi = div(gross_margin_prev, gross_margin)
    aqi_current = (
        None
        if assets is None or current_assets is None or ppe is None or assets == 0
        else 1.0 - (current_assets + ppe) / assets
    )
    aqi_prev = (
        None
        if assets_prev is None or current_assets_prev is None or ppe_prev is None or assets_prev == 0
        else 1.0 - (current_assets_prev + ppe_prev) / assets_prev
    )
    aqi = div(aqi_current, aqi_prev)
    sgi = div(revenue, revenue_prev)
    dep_rate = div(depreciation, None if depreciation is None or ppe is None else depreciation + ppe)
    dep_rate_prev = div(
        depreciation_prev,
        None if depreciation_prev is None or ppe_prev is None else depreciation_prev + ppe_prev,
    )
    depi = div(dep_rate_prev, dep_rate)
    sgai = div(div(sga, revenue), div(sga_prev, revenue_prev))
    lvgi = div(div(liabilities, assets), div(liabilities_prev, assets_prev))
    tata = (
        None
        if net_income is None or cfo is None or assets is None or assets == 0
        else (net_income - cfo) / assets
    )
    components = {
        "DSRI": dsri,
        "GMI": gmi,
        "AQI": aqi,
        "SGI": sgi,
        "DEPI": depi,
        "SGAI": sgai,
        "TATA": tata,
        "LVGI": lvgi,
    }
    available = [value for value in components.values() if value is not None and math.isfinite(value)]
    coverage = len(available) / 8.0
    if len(available) < 8:
        return {
            "value": None,
            "coverage": round(coverage, 2),
            "label": "Kısmi veri" if len(available) >= 6 else "Veri yetersiz",
            "components": components,
        }

    value = (
        -4.84
        + 0.920 * dsri
        + 0.528 * gmi
        + 0.404 * aqi
        + 0.892 * sgi
        + 0.115 * depi
        - 0.172 * sgai
        + 4.679 * tata
        - 0.327 * lvgi
    )
    label = "Düşük manipülasyon sinyali" if value < -1.78 else "Yakın izleme"
    return {
        "value": round(float(value), 3),
        "coverage": 1.0,
        "label": label,
        "components": components,
    }


def enrich_beneish(
    financial: dict[str, Any],
    fundamental: FundamentalReport,
    balance: pd.DataFrame,
    income: pd.DataFrame,
    cashflow: pd.DataFrame | None,
) -> dict[str, Any]:
    """Replace the placeholder Beneish field using the same statements as core research."""
    result = dict(financial)
    scores = dict(financial.get("forensic_scores") or {})
    if fundamental.profile == "BANK":
        scores["beneish_m"] = {"value": None, "coverage": 0.0, "label": "Bankalarda uygulanmaz"}
        result["forensic_scores"] = scores
        return result

    b = {
        key: ext._vals(balance, key)
        for key in ("assets", "current_assets", "equity", "receivables", "liabilities", "ppe")
    }
    i = {
        key: ext._vals(income, key)
        for key in ("revenue", "gross_profit", "net_income", "depreciation", "sga")
    }
    cfo_values = ext._vals(cashflow, "cfo") if cashflow is not None else []

    assets, assets_prev = ext._latest(b["assets"]), ext._latest(b["assets"], 4)
    current_assets, current_assets_prev = ext._latest(b["current_assets"]), ext._latest(b["current_assets"], 4)
    equity, equity_prev = ext._latest(b["equity"]), ext._latest(b["equity"], 4)
    liabilities, liabilities_prev = ext._latest(b["liabilities"]), ext._latest(b["liabilities"], 4)
    if liabilities is None and assets is not None and equity is not None:
        liabilities = assets - equity
    if liabilities_prev is None and assets_prev is not None and equity_prev is not None:
        liabilities_prev = assets_prev - equity_prev

    scores["beneish_m"] = _beneish(
        revenue=ext._sum4(i["revenue"]),
        revenue_prev=ext._sum4(i["revenue"], 4),
        receivables=ext._latest(b["receivables"]),
        receivables_prev=ext._latest(b["receivables"], 4),
        gross_profit=ext._sum4(i["gross_profit"]),
        gross_profit_prev=ext._sum4(i["gross_profit"], 4),
        current_assets=current_assets,
        current_assets_prev=current_assets_prev,
        ppe=ext._latest(b["ppe"]),
        ppe_prev=ext._latest(b["ppe"], 4),
        assets=assets,
        assets_prev=assets_prev,
        depreciation=ext._sum4(i["depreciation"]),
        depreciation_prev=ext._sum4(i["depreciation"], 4),
        sga=ext._sum4(i["sga"]),
        sga_prev=ext._sum4(i["sga"], 4),
        liabilities=liabilities,
        liabilities_prev=liabilities_prev,
        net_income=ext._sum4(i["net_income"]),
        cfo=ext._sum4(cfo_values),
    )
    result["forensic_scores"] = scores
    return result


def _positive_multiple(value: Any) -> float | None:
    number = core._finite(value)
    if number is None or number <= 0 or number >= 10_000:
        return None
    return number


def sanitize_valuation(valuation: dict[str, Any]) -> dict[str, Any]:
    """Remove multiple sentinels without deriving or overwriting raw yield fields."""
    result = dict(valuation)
    metrics = {
        key: dict(value) if isinstance(value, dict) else value
        for key, value in valuation.get("metrics", {}).items()
    }
    for key in VALUATION_MULTIPLES:
        item = metrics.get(key)
        if not isinstance(item, dict):
            continue
        item["value"] = _positive_multiple(item.get("value"))
        metrics[key] = item

    peer = dict(valuation.get("peer_analysis") or {})
    clean_peers: list[dict[str, Any]] = []
    for raw_peer in peer.get("peers", ()):
        item = dict(raw_peer)
        for key in PEER_MULTIPLES:
            item[key] = _positive_multiple(item.get(key))
        clean_peers.append(item)
    peer["peers"] = clean_peers

    result["metrics"] = metrics
    result["peer_analysis"] = peer
    result["multiple_quality_note"] = (
        "Negatif veya 10.000x ve üzeri sağlayıcı sentinel çarpanları N/M kabul edilir. "
        "Kazanç ve FCF verimleri ham finansallardan korunur; provider fallback çarpanlarıyla "
        "uyuşmazlık varsa değerlerden biri diğerine zorla eşitlenmez."
    )
    return result


def sanitize_profile_financials(financial: dict[str, Any], profile: str) -> dict[str, Any]:
    """Hide non-comparable GYO margins while retaining their raw values for audit."""
    if profile != "GYO":
        return financial

    result = dict(financial)
    metrics = dict(financial.get("metrics") or {})
    raw_non_comparable: dict[str, float] = {}
    for key in (
        "operating_margin",
        "operating_margin_quarterly",
        "net_margin",
        "net_margin_quarterly",
    ):
        value = core._finite(metrics.get(key))
        if value is not None and abs(value) > GYO_NON_COMPARABLE_MARGIN_LIMIT:
            raw_non_comparable[key] = value
            metrics[key] = None

    if raw_non_comparable:
        result["non_comparable_metrics"] = raw_non_comparable
        result["ratio_note"] = (
            str(result.get("ratio_note", ""))
            + " GYO'da yatırım amaçlı gayrimenkul değerleme/tek seferlik faaliyet kalemleri nedeniyle "
            "ekonomik olarak karşılaştırılamayan aşırı marjlar kartta N/M bırakılır; ham değer JSON'da korunur."
        ).strip()

    result["metrics"] = metrics
    ratio_groups = []
    for group in result.get("ratio_groups", ()):
        group_copy = dict(group)
        rows = []
        for row in group.get("rows", ()):
            row_copy = dict(row)
            row_copy["value"] = metrics.get(row_copy.get("key"))
            rows.append(row_copy)
        group_copy["rows"] = tuple(rows)
        ratio_groups.append(group_copy)
    result["ratio_groups"] = tuple(ratio_groups)
    return result
