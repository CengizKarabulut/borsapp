"""Canonical news ingestion contracts and providers."""

from market_intelligence.news.contracts import NewsItem
from market_intelligence.news.general import GeneralNewsProvider
from market_intelligence.news.kap import KapDisclosureProvider

__all__ = ["GeneralNewsProvider", "KapDisclosureProvider", "NewsItem"]
