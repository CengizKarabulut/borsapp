"""Deprecated import path for the native general-news provider."""

from market_intelligence.news.general import (
    SUPPORTED_SOURCES,
    GeneralNewsProvider,
    LegacyGeneralNewsProvider,
)

__all__ = [
    "GeneralNewsProvider",
    "LegacyGeneralNewsProvider",
    "SUPPORTED_SOURCES",
]
