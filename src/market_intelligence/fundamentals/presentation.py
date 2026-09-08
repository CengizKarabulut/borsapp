from __future__ import annotations

from market_intelligence.fundamentals.providers import FinancialSnapshot


def _number(value: float | None) -> str:
    if value is None:
        return "UNKNOWN"
    magnitude = abs(value)
    if magnitude >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f} mlr"
    if magnitude >= 1_000_000:
        return f"{value / 1_000_000:.2f} mn"
    return f"{value:.2f}"


def _pct(value: float | None) -> str:
    return "UNKNOWN" if value is None else f"%{value:+.2f}"


def fundamental_message(symbol: str, snapshot: FinancialSnapshot | None) -> str:
    if snapshot is None:
        return (
            f"{symbol} · temel analiz\n"
            "BIST/KAP bilanço adapteri ve yfinance fallback veri döndürmedi. "
            "Eksik alanlar tahmin edilmedi."
        )
    metric = snapshot.metrics.get
    providers = ", ".join(snapshot.providers_used)
    return (
        f"{symbol} · temel analiz\n"
        f"Şirket: {snapshot.company_name or 'UNKNOWN'}\n"
        f"Sektör: {snapshot.sector or 'UNKNOWN'} · Para birimi: {snapshot.currency or 'UNKNOWN'}\n"
        f"Kaynak: {providers} · Kapsam: %{snapshot.coverage * 100:.0f}\n\n"
        f"TTM hasılat: {_number(metric('revenue_ttm'))} · büyüme {_pct(metric('revenue_growth'))}\n"
        f"TTM net kâr: {_number(metric('net_income_ttm'))} · marj {_pct(metric('net_margin'))}\n"
        f"TTM CFO: {_number(metric('cfo_ttm'))} · FCF {_number(metric('fcf_ttm'))}\n"
        f"Varlıklar: {_number(metric('assets'))} · özkaynak {_number(metric('equity'))}\n"
        f"Net borç: {_number(metric('net_debt'))} · cari oran {_number(metric('current_ratio'))}\n"
        f"ROE: {_pct(metric('roe'))} · ROA: {_pct(metric('roa'))}\n"
        f"F/K: {_number(metric('pe'))} · PD/DD: {_number(metric('pb'))} · "
        f"FD/FAVÖK: {_number(metric('ev_ebitda'))}\n\n"
        "Çarpanlar hedef fiyat değildir. UNKNOWN alanlar tahmin edilmemiştir; yatırım tavsiyesi değildir."
    )
