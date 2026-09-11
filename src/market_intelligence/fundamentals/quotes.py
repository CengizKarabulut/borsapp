"""Observed quotes with honest exchange-time metadata and provider fallback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from market_intelligence.fundamentals.providers import FinancialSnapshot, _finite


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    price: float
    currency: str
    source: str
    observed_at: datetime
    market_time: datetime | None = None
    shares: float | None = None

    def __post_init__(self):
        if _finite(self.price) is None or self.price <= 0:
            raise ValueError("Quote price must be finite and positive")
        if not self.currency or self.observed_at.tzinfo is None:
            raise ValueError("Currency and timezone-aware observation are required")
        if self.market_time is not None and self.market_time.tzinfo is None:
            raise ValueError("Market timestamp must include timezone")


class MarketQuoteProvider:
    def __init__(
        self,
        *,
        borsapy_factory=None,
        yfinance_factory=None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.borsapy_factory = borsapy_factory
        self.yfinance_factory = yfinance_factory
        self.clock = clock

    def fetch(self, symbol: str) -> MarketQuote:
        canonical = symbol.upper().removesuffix(".IS")
        try:
            if self.borsapy_factory is None:
                import borsapy

                ticker = borsapy.Ticker(canonical)
            else:
                ticker = self.borsapy_factory(canonical)
            info = ticker.info
            price = _finite(info.get("last") or info.get("regularMarketPrice"))
            # A clock-only update_time is not a dated market timestamp.
            # Do not label it as live or assert a 15 minute delay.
            currency = info.get("currency")
            if price is not None and price > 0 and currency:
                return MarketQuote(
                    canonical,
                    price,
                    str(currency),
                    "borsapy",
                    self.clock(),
                    shares=_finite(info.get("sharesOutstanding")),
                )
        except Exception:
            pass
        if self.yfinance_factory is None:
            import yfinance

            ticker = yfinance.Ticker(canonical + ".IS")
        else:
            ticker = self.yfinance_factory(canonical + ".IS")
        info = ticker.info
        stamp = _finite(info.get("regularMarketTime"))
        return MarketQuote(
            canonical,
            _finite(info.get("regularMarketPrice")),
            str(info.get("currency") or ""),
            "yfinance",
            self.clock(),
            datetime.fromtimestamp(stamp, UTC) if stamp is not None else None,
            _finite(info.get("sharesOutstanding")),
        )


def apply_quote(snapshot: FinancialSnapshot, quote: MarketQuote) -> FinancialSnapshot:
    if quote.symbol != snapshot.symbol:
        raise ValueError("Quote symbol mismatch")
    metadata = {
        **snapshot.metadata,
        "quote_price": quote.price,
        "quote_source": quote.source,
        "quote_currency": quote.currency,
        "quote_observed_at": quote.observed_at.isoformat(),
        "quote_market_time": quote.market_time.isoformat() if quote.market_time else None,
        "quote_delay": "unknown",
    }
    if snapshot.currency != quote.currency:
        return replace(
            snapshot, metadata=metadata, errors=(*snapshot.errors, "quote:currency_mismatch")
        )
    metrics = dict(snapshot.metrics)
    sources = dict(snapshot.metric_sources)
    shares = quote.shares if quote.shares is not None else metrics.get("shares_outstanding")
    if _finite(shares) is not None and shares > 0:
        metrics["shares_outstanding"] = shares
        metrics["market_cap"] = quote.price * shares
        sources["market_cap"] = quote.source + ":price*total_shares"
        if quote.shares is not None:
            sources["shares_outstanding"] = quote.source
    else:
        metrics["market_cap"] = None
    cap = metrics.get("market_cap")
    debt = metrics.get("net_debt")
    ev = cap + debt if cap is not None and debt is not None else None
    metrics["enterprise_value"] = ev
    for key, numerator, denominator in (
        ("pe", cap, metrics.get("net_income_ttm")),
        ("pb", cap, metrics.get("equity")),
        ("ev_ebitda", ev, metrics.get("ebitda_ttm")),
        ("ev_sales", ev, metrics.get("revenue_ttm")),
        ("fcf_yield", metrics.get("fcf_ttm"), cap),
        ("earnings_yield", metrics.get("net_income_ttm"), cap),
    ):
        value = (
            numerator / denominator
            if numerator is not None and denominator is not None and denominator > 0
            else None
        )
        if value is not None and key.endswith("yield"):
            value *= 100
        metrics[key] = value
        if value is not None:
            sources[key] = quote.source + ":quote+financial_statements"
        else:
            sources.pop(key, None)
    return replace(snapshot, metrics=metrics, metric_sources=sources, metadata=metadata)
