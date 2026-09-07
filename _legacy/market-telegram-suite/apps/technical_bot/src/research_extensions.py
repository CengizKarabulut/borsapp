"""PR #13 financial/peer extensions rebuilt on main's raw-first valuation policy."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from src import research_engine as core
from src.fundamental_analysis import FundamentalReport

EXTRA_ALIASES = {
    "liabilities": ("total liabilities", "liabilities total", "toplam yukumlulukler", "toplam borclar"),
    "ppe": ("property plant and equipment", "property plant equipment", "maddi duran varliklar"),
    "retained_earnings": ("retained earnings", "accumulated profits losses", "gecmis yillar karlari"),
    "paid_in_capital": ("issued capital", "paid in capital", "share capital", "odenmis sermaye"),
    "depreciation": ("depreciation and amortization", "depreciation amortization", "amortisman giderleri"),
    "sga": ("selling general administrative expenses", "selling general and administrative expenses", "genel yonetim giderleri"),
}

RATIO_GROUPS = (
    ("Likidite Oranları", (("current_ratio", "Cari Oran", "x"), ("quick_ratio", "Likidite Oranı", "x"), ("cash_ratio", "Nakit Oran", "x"))),
    ("Kaldıraç Oranları", (("financial_debt_ratio", "Finansal Borç Oranı", "%"), ("leverage_ratio", "Kaldıraç Oranı", "x"), ("liabilities_equity", "Toplam Borç / Özkaynak", "x"), ("net_debt_ebitda", "Net Borç / FAVÖK", "x"), ("interest_coverage", "Faiz Karşılama", "x"))),
    ("Faaliyet Etkinlik Oranları", (("asset_turnover", "Aktif Devir Hızı", "x"), ("inventory_turnover", "Stok Devir Hızı", "x"), ("payables_turnover", "Borç Devir Hızı", "x"), ("equity_turnover", "Özkaynak Devir Hızı", "x"), ("receivables_turnover", "Alacak Devir Hızı", "x"))),
    ("Kârlılık Oranları", (("roa", "Aktif Kârlılık", "%"), ("gross_margin", "Brüt Kâr Marjı", "%"), ("ebitda_margin", "FAVÖK Marjı", "%"), ("operating_margin", "Esas Faaliyet Kâr Marjı", "%"), ("net_margin", "Net Kâr Marjı", "%"), ("roe", "Özkaynak Kârlılığı", "%"), ("roic", "ROIC", "%"), ("eps", "Hisse Başına Kâr", "₺"))),
)


def _finite(value: Any) -> float | None:
    return core._finite(value)


def _series(frame: pd.DataFrame | None, key: str) -> pd.Series | None:
    if key in core.STATEMENT_ALIASES:
        return core._statement_series(frame, key)
    if frame is None or frame.empty:
        return None
    aliases = EXTRA_ALIASES.get(key, ())
    labels = [(core._norm(idx), idx) for idx in frame.index]
    for alias in aliases:
        target = core._norm(alias)
        matches = [idx for label, idx in labels if label == target]
        if not matches:
            matches = [idx for label, idx in labels if target and target in label]
        if matches:
            selected = frame.loc[matches[0]]
            rows = selected if isinstance(selected, pd.DataFrame) else pd.DataFrame([selected])
            rows = rows.apply(pd.to_numeric, errors="coerce")
            row = max((item for _, item in rows.iterrows()), key=lambda item: int(item.notna().sum()), default=None)
            if row is None:
                return None
            return row.reindex(sorted(row.index, key=core._period_key))
    return None


def _vals(frame: pd.DataFrame | None, key: str) -> list[float | None]:
    return core._values(_series(frame, key))


def _latest(values: list[float | None], lag: int = 0) -> float | None:
    return core._latest(values, lag)


def _sum4(values: list[float | None], offset: int = 0) -> float | None:
    return core._sum4(values, offset)


def _ratio(num: float | None, den: float | None, scale: float = 1.0) -> float | None:
    if num is None or den is None or abs(den) < 1e-9:
        return None
    return num / den * scale


def _multiple(num: float | None, den: float | None) -> float | None:
    """Valuation multiple: non-positive denominator is economically N/M."""
    return None if num is None or den is None or den <= 0 else num / den


def _raw_or_provider(num: float | None, den: float | None, provider: float | None) -> float | None:
    """Use provider only if at least one required raw input is genuinely missing."""
    return _multiple(num, den) if num is not None and den is not None else provider


def _avg(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else (a + b) / 2.0


def _market_snapshot(symbol: str, price: float | None) -> dict[str, float | None]:
    try:
        import borsapy as bp

        stock = bp.Ticker(symbol)
        try:
            fast = dict(stock.fast_info or {})
        except Exception:  # noqa: BLE001
            fast = {}
        try:
            info = dict(stock.info or {})
        except Exception:  # noqa: BLE001
            info = {}
    except Exception:  # noqa: BLE001
        return {"market_cap": None, "enterprise_value": None, "shares_outstanding": None}

    def pick(mapping: dict[str, Any], *names: str) -> float | None:
        for name in names:
            value = _finite(mapping.get(name))
            if value is not None and value > 0:
                return value
        return None

    market_cap = pick(fast, "market_cap", "marketCap") or pick(info, "marketCap", "market_cap")
    enterprise = pick(info, "enterpriseValue", "enterprise_value")
    shares = pick(info, "sharesOutstanding", "shares_outstanding", "impliedSharesOutstanding") or pick(fast, "shares", "shares_outstanding")
    if shares is None and market_cap is not None and price is not None and price > 0:
        shares = market_cap / price
    return {"market_cap": market_cap, "enterprise_value": enterprise, "shares_outstanding": shares}


def _beta(symbol: str) -> float | None:
    try:
        import borsapy as bp

        stock = bp.Ticker(symbol).history(period="1y", interval="1d")
        benchmark = bp.Ticker("XU100").history(period="1y", interval="1d")
        if stock is None or benchmark is None or stock.empty or benchmark.empty:
            return None
        scol = "Close" if "Close" in stock.columns else "close"
        bcol = "Close" if "Close" in benchmark.columns else "close"
        joined = pd.concat(
            [pd.to_numeric(stock[scol], errors="coerce").pct_change().rename("stock"), pd.to_numeric(benchmark[bcol], errors="coerce").pct_change().rename("market")],
            axis=1,
        ).dropna()
        if len(joined) < 80 or float(joined["market"].var()) <= 0:
            return None
        return float(joined["stock"].cov(joined["market"]) / joined["market"].var())
    except Exception:  # noqa: BLE001
        return None


def _piotroski(metrics: dict[str, float | None], previous: dict[str, float | None]) -> dict[str, Any]:
    checks = {
        "positive_roa": None if metrics.get("roa") is None else metrics["roa"] > 0,
        "positive_cfo": None if metrics.get("cfo_ttm") is None else metrics["cfo_ttm"] > 0,
        "roa_improving": None if metrics.get("roa") is None or previous.get("roa") is None else metrics["roa"] > previous["roa"],
        "cash_exceeds_profit": None if metrics.get("cfo_ttm") is None or metrics.get("net_income_ttm") is None else metrics["cfo_ttm"] > metrics["net_income_ttm"],
        "leverage_improving": None if metrics.get("financial_debt_ratio") is None or previous.get("financial_debt_ratio") is None else metrics["financial_debt_ratio"] < previous["financial_debt_ratio"],
        "liquidity_improving": None if metrics.get("current_ratio") is None or previous.get("current_ratio") is None else metrics["current_ratio"] > previous["current_ratio"],
        "gross_margin_improving": None if metrics.get("gross_margin") is None or previous.get("gross_margin") is None else metrics["gross_margin"] > previous["gross_margin"],
        "asset_turnover_improving": None if metrics.get("asset_turnover") is None or previous.get("asset_turnover") is None else metrics["asset_turnover"] > previous["asset_turnover"],
    }
    observed = [value for value in checks.values() if value is not None]
    score = sum(bool(value) for value in observed)
    return {"score": score if observed else None, "max_score": len(observed), "coverage": round(len(observed) / 9.0, 2), "official_score": None, "criteria": checks, "note": "Eksik Piotroski ölçütleri puanlanmaz; kısmi skor gözlenen/max olarak gösterilir."}


def _altman(metrics: dict[str, float | None]) -> dict[str, Any]:
    required = [metrics.get(key) for key in ("assets", "liabilities", "working_capital", "retained_earnings", "operating_profit_ttm", "market_cap", "revenue_ttm")]
    coverage = sum(value is not None for value in required) / len(required)
    assets, liabilities, wc, retained, ebit, market_cap, revenue = required
    if assets is None or assets <= 0 or liabilities is None or liabilities <= 0 or any(value is None for value in (wc, retained, ebit, market_cap, revenue)):
        return {"value": None, "coverage": round(coverage, 2), "label": "Veri yetersiz"}
    value = 1.2 * wc / assets + 1.4 * retained / assets + 3.3 * ebit / assets + 0.6 * market_cap / liabilities + revenue / assets
    label = "Görece güçlü" if value > 2.99 else "Gri bölge" if value >= 1.81 else "Finansal baskı"
    return {"value": round(value, 3), "coverage": 1.0, "label": label}


def enrich_financial_analysis(base: dict[str, Any], fundamental: FundamentalReport, balance: pd.DataFrame, income: pd.DataFrame, cashflow: pd.DataFrame | None) -> dict[str, Any]:
    """Add PR #13 statement ratios/forensic payload without changing main scoring."""
    out = dict(base)
    metrics = dict(base.get("metrics", {}))
    market = _market_snapshot(fundamental.symbol, fundamental.price)
    if fundamental.profile == "BANK":
        metrics.update({key: value for key, value in fundamental.metrics.items() if key not in metrics})
        metrics.update(market)
        metrics["beta"] = _beta(fundamental.symbol)
        out.update({"metrics": metrics, "ratio_groups": (), "forensic_scores": {"altman_z": {"value": None, "coverage": 0.0, "label": "Bankalarda uygulanmaz"}, "beneish_m": {"value": None, "coverage": 0.0, "label": "Bankalarda uygulanmaz"}, "graham_number": {"value": None, "coverage": 0.0, "label": "Bankalarda sınırlı anlam"}, "piotroski_f": {"score": None, "max_score": 0, "coverage": 0.0, "official_score": None, "criteria": {}}, "beta": {"value": metrics.get("beta"), "coverage": 1.0 if metrics.get("beta") is not None else 0.0}}, "ratio_note": "Endüstriyel şirket oranları banka profiline zorla uygulanmaz."})
        return out

    b = {key: _vals(balance, key) for key in ("assets", "current_assets", "current_liabilities", "equity", "cash", "inventory", "receivables", "payables", "short_debt", "current_long_debt", "long_debt", "liabilities", "retained_earnings")}
    i = {key: _vals(income, key) for key in ("revenue", "gross_profit", "operating_profit", "ebitda", "net_income", "finance_expense")}
    c = {key: _vals(cashflow, key) for key in ("cfo", "capex")} if cashflow is not None else {"cfo": [], "capex": []}

    assets, assets_prev = _latest(b["assets"]), _latest(b["assets"], 4)
    current_assets, current_assets_prev = _latest(b["current_assets"]), _latest(b["current_assets"], 4)
    current_liabilities, current_liabilities_prev = _latest(b["current_liabilities"]), _latest(b["current_liabilities"], 4)
    equity, equity_prev = _latest(b["equity"]), _latest(b["equity"], 4)
    cash, inventory = _latest(b["cash"]), _latest(b["inventory"])
    receivables, receivables_prev = _latest(b["receivables"]), _latest(b["receivables"], 4)
    payables, payables_prev = _latest(b["payables"]), _latest(b["payables"], 4)
    liabilities = _latest(b["liabilities"])
    if liabilities is None and assets is not None and equity is not None:
        liabilities = assets - equity
    debt_parts = (_latest(b["short_debt"]), _latest(b["current_long_debt"]), _latest(b["long_debt"]))
    debt = sum(value or 0.0 for value in debt_parts) if any(value is not None for value in debt_parts) else None
    debt_prev_parts = (_latest(b["short_debt"], 4), _latest(b["current_long_debt"], 4), _latest(b["long_debt"], 4))
    debt_prev = sum(value or 0.0 for value in debt_prev_parts) if any(value is not None for value in debt_prev_parts) else None

    revenue, revenue_prev = _sum4(i["revenue"]), _sum4(i["revenue"], 4)
    gross, gross_prev = _sum4(i["gross_profit"]), _sum4(i["gross_profit"], 4)
    operating, ebitda, net_income = _sum4(i["operating_profit"]), _sum4(i["ebitda"]), _sum4(i["net_income"])
    net_prev, finance, cfo, capex = _sum4(i["net_income"], 4), _sum4(i["finance_expense"]), _sum4(c["cfo"]), _sum4(c["capex"])
    fcf = None if cfo is None else cfo - abs(capex or 0.0)
    avg_assets, avg_equity = _avg(assets, assets_prev), _avg(equity, equity_prev)
    cogs = None if revenue is None or gross is None else revenue - gross
    avg_inventory = _avg(inventory, _latest(b["inventory"], 4))
    avg_receivables, avg_payables = _avg(receivables, receivables_prev), _avg(payables, payables_prev)

    current_ratio = _ratio(current_assets, current_liabilities)
    previous_current_ratio = _ratio(current_assets_prev, current_liabilities_prev)
    values = {
        "current_ratio": current_ratio,
        "quick_ratio": _ratio(None if current_assets is None or inventory is None else current_assets - inventory, current_liabilities),
        "cash_ratio": _ratio(cash, current_liabilities),
        "financial_debt_ratio": _ratio(debt, assets, 100.0),
        "leverage_ratio": _ratio(assets, equity),
        "liabilities_equity": _ratio(liabilities, equity),
        "asset_turnover": _ratio(revenue, avg_assets),
        "inventory_turnover": _ratio(cogs, avg_inventory),
        "payables_turnover": _ratio(cogs, avg_payables),
        "equity_turnover": _ratio(revenue, avg_equity),
        "receivables_turnover": _ratio(revenue, avg_receivables),
        "roa": _ratio(net_income, avg_assets, 100.0),
        "roe": _ratio(net_income, avg_equity, 100.0),
        "gross_margin": _ratio(gross, revenue, 100.0),
        "ebitda_margin": _ratio(ebitda, revenue, 100.0),
        "operating_margin": _ratio(operating, revenue, 100.0),
        "net_margin": _ratio(net_income, revenue, 100.0),
        "net_debt_ebitda": _ratio(None if debt is None else debt - (cash or 0.0), ebitda),
        "interest_coverage": _ratio(operating, abs(finance)) if finance not in (None, 0) else None,
        "revenue_ttm": revenue,
        "operating_profit_ttm": operating,
        "ebitda_ttm": ebitda,
        "net_income_ttm": net_income,
        "cfo_ttm": cfo,
        "fcf_ttm": fcf,
        "assets": assets,
        "equity": equity,
        "liabilities": liabilities,
        "total_financial_debt": debt,
        "cash": cash,
        "market_cap": market.get("market_cap"),
        "provider_enterprise_value": market.get("enterprise_value"),
        "shares_outstanding": market.get("shares_outstanding"),
        "retained_earnings": _latest(b["retained_earnings"]),
        "working_capital": None if current_assets is None or current_liabilities is None else current_assets - current_liabilities,
    }
    values["eps"] = _ratio(net_income, values["shares_outstanding"])
    values["book_value_per_share"] = _ratio(equity, values["shares_outstanding"])
    values["roic"] = _ratio(operating, None if equity is None or debt is None else equity + debt - (cash or 0.0), 100.0)
    values["beta"] = _beta(fundamental.symbol)
    metrics.update(values)

    previous = {
        "roa": _ratio(net_prev, assets_prev, 100.0),
        "financial_debt_ratio": _ratio(debt_prev, assets_prev, 100.0),
        "current_ratio": previous_current_ratio,
        "gross_margin": _ratio(gross_prev, revenue_prev, 100.0),
        "asset_turnover": _ratio(revenue_prev, assets_prev),
    }
    graham = None
    if values["eps"] is not None and values["book_value_per_share"] is not None and values["eps"] > 0 and values["book_value_per_share"] > 0:
        graham = math.sqrt(22.5 * values["eps"] * values["book_value_per_share"])

    out["metrics"] = metrics
    out["ratio_groups"] = tuple({"name": name, "rows": tuple({"key": key, "label": label, "unit": unit, "value": metrics.get(key)} for key, label, unit in rows)} for name, rows in RATIO_GROUPS)
    out["forensic_scores"] = {
        "altman_z": _altman(metrics),
        "beneish_m": {"value": None, "coverage": 0.0, "label": "Tam 8 bileşen yoksa üretilmez"},
        "graham_number": {"value": None if graham is None else round(graham, 3), "coverage": 1.0 if graham is not None else 0.0, "label": "Graham sayısı"},
        "piotroski_f": _piotroski(metrics, previous),
        "beta": {"value": None if metrics["beta"] is None else round(metrics["beta"], 3), "coverage": 1.0 if metrics["beta"] is not None else 0.0, "label": "BIST 100'e göre 1 yıllık günlük beta"},
    }
    out["ratio_note"] = "Oranlar son 4 çeyrek (TTM) ve son bilanço üzerinden hesaplanır; eksik veri değer uydurmaz."
    return out


def _provider(detail: dict[str, Any], key: str) -> float | None:
    item = detail.get(key)
    return _finite(item.get("value")) if isinstance(item, dict) else None


def _set(detail: dict[str, Any], key: str, value: float | None, percentile: float | None = None) -> None:
    item = dict(detail.get(key, {})) if isinstance(detail.get(key), dict) else {}
    item.update({"value": value, "percentile": percentile})
    detail[key] = item


def enrich_valuation(valuation: dict[str, Any], financial: dict[str, Any], *, symbol: str, profile: str) -> dict[str, Any]:
    """Expand multiples/peers, preserving #19 raw-first + non-positive=N/M policy."""
    result = dict(valuation)
    detail = {key: dict(value) if isinstance(value, dict) else value for key, value in valuation.get("metrics", {}).items()}
    fm = financial.get("metrics", {})
    market_cap, debt, cash = (_finite(fm.get(key)) for key in ("market_cap", "total_financial_debt", "cash"))
    raw_ev = market_cap is not None and debt is not None and cash is not None
    enterprise = market_cap + debt - cash if raw_ev else _finite(fm.get("provider_enterprise_value"))
    revenue, ebitda, net_income, equity, fcf = (_finite(fm.get(key)) for key in ("revenue_ttm", "ebitda_ttm", "net_income_ttm", "equity", "fcf_ttm"))

    pe = _raw_or_provider(market_cap, net_income, _provider(detail, "pe"))
    pb = _raw_or_provider(market_cap, equity, _provider(detail, "pb"))
    ev_ebitda = _multiple(enterprise, ebitda) if raw_ev and ebitda is not None else _provider(detail, "ev_ebitda")
    ev_sales = _multiple(enterprise, revenue) if raw_ev and revenue is not None else _provider(detail, "ev_sales")
    ps = _raw_or_provider(market_cap, revenue, _provider(detail, "ps"))
    p_fcf = _raw_or_provider(market_cap, fcf, _provider(detail, "p_fcf"))
    earnings_yield = net_income / market_cap * 100.0 if market_cap is not None and market_cap > 0 and net_income is not None else _provider(detail, "earnings_yield")
    fcf_yield = fcf / market_cap * 100.0 if market_cap is not None and market_cap > 0 and fcf is not None else _provider(detail, "fcf_yield")
    growth = _finite(fm.get("net_income_growth"))
    if market_cap is not None and net_income is not None:
        peg = pe / growth if pe is not None and growth is not None and growth > 0 else None
    else:
        peg = _provider(detail, "peg")
    final = {"pe": pe, "pb": pb, "ev_ebitda": ev_ebitda, "ev_sales": ev_sales, "ps": ps, "p_fcf": p_fcf, "peg": peg, "earnings_yield": earnings_yield, "fcf_yield": fcf_yield}
    for key, value in final.items():
        _set(detail, key, value)

    score_metrics = ["pe", "pb"] if profile == "BANK" else ["pb", "pe"] if profile == "GYO" else ["pe", "pb", "ev_ebitda", "ev_sales"]
    peer_analysis: dict[str, Any] = {"scope": result.get("scope", "—"), "peer_count": 0, "peers": [], "benchmarks": {}}
    scores: list[tuple[float | None, float]] = []
    try:
        frame = core._fetch_peer_snapshot()
        target_row = frame[frame["symbol"] == symbol]
        if not target_row.empty:
            sector = str(target_row.iloc[0].get("sector") or "GENERIC")
            industry = str(target_row.iloc[0].get("industry") or "")
            industry_peers = frame[frame["industry"] == industry] if industry and "industry" in frame.columns else pd.DataFrame()
            sector_peers = frame[frame["sector"] == sector] if sector != "GENERIC" else pd.DataFrame()
            peers = industry_peers if len(industry_peers) >= 5 else sector_peers if len(sector_peers) >= 8 else frame
            scope = f"{industry} endüstrisi" if len(industry_peers) >= 5 else f"{sector} sektörü" if len(sector_peers) >= 8 else "BIST geneli"
            benchmarks = {}
            for metric in (*score_metrics, "roe"):
                series = pd.to_numeric(peers[metric], errors="coerce").where(lambda x: x > 0).dropna() if metric in peers.columns and metric != "roe" else pd.to_numeric(peers[metric], errors="coerce").dropna() if metric in peers.columns else pd.Series(dtype=float)
                target = _finite(final.get(metric)) if metric in final else _finite(fm.get(metric))
                if len(series) < 5 or target is None or (metric != "roe" and target <= 0):
                    if metric in score_metrics:
                        scores.append((None, 1.0))
                    benchmarks[metric] = {"median": float(series.median()) if len(series) else None, "target": target, "percentile": None}
                    continue
                percentile = round(float((series <= target).mean() * 100.0), 1)
                benchmarks[metric] = {"median": float(series.median()), "q1": float(series.quantile(0.25)), "q3": float(series.quantile(0.75)), "target": target, "percentile": percentile}
                if metric in score_metrics:
                    scores.append((100.0 - percentile, 1.0))
                    _set(detail, metric, target, percentile)
            selected = peers.assign(_mc=pd.to_numeric(peers.get("market_cap"), errors="coerce")).sort_values("_mc", ascending=False, na_position="last").head(8) if "market_cap" in peers.columns else peers.head(8)
            payload = []
            for _, row in selected.iterrows():
                item = {"symbol": str(row.get("symbol", "")), "name": str(row.get("name", "") or "")}
                item.update({metric: _finite(row.get(metric)) for metric in ("market_cap", "pe", "pb", "ev_ebitda", "ev_sales", "roe")})
                payload.append(item)
            peer_analysis = {"scope": scope, "sector": sector, "industry": industry, "peer_count": int(len(peers)), "peers": payload, "benchmarks": benchmarks}
            result.update({"scope": scope, "sector": sector})
    except Exception as exc:  # noqa: BLE001
        peer_analysis["error"] = type(exc).__name__

    if not scores:
        scores = [(None, 1.0) for _ in score_metrics]
    score, coverage = core._weighted(scores)
    result.update({"score": score, "coverage": coverage, "metrics": detail, "peer_analysis": peer_analysis})
    result["calculated_multiples"] = {"market_cap": market_cap, "enterprise_value": enterprise, **final}
    result["peg_note"] = "PEG ham-öncelikli F/K ve pozitif son 4 çeyrek net kâr büyümesiyle hesaplanır; aksi halde N/M'dir."
    if profile == "BANK":
        result["note"] = "Banka değerlemesinde F/K, PD/DD ve ROE ana eksendir; endüstriyel firma değeri çarpanları zorlanmaz."
    elif profile == "GYO":
        result["note"] = "GYO'da PD/DD ve kârlılık çarpanları ikincil bağlamdır; ekspertiz/NAD olmadan PD/NAD üretilmez."
    else:
        result["note"] = "Hedef şirket çarpanlarında ham veri önceliklidir; provider yalnız ham girdi eksikse fallback'tir. Non-positive payda N/M'dir."
    return result
