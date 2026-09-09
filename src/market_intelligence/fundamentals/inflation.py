"""Point-in-time Turkish CPI provider used for real growth commentary."""

from __future__ import annotations

import calendar
import math
from collections.abc import Callable
from datetime import datetime
from typing import Any, Protocol

import pandas as pd


class InflationDataProvider(Protocol):
    provider_id: str

    def fetch_yoy(self, *, period_end: datetime) -> float | None: ...


class BorsapyTcmbInflationProvider:
    """Read the official TCMB-backed TÜFE observation for a financial period."""

    provider_id = "borsapy:tcmb_tufe"

    def __init__(self, source_factory: Callable[[], Any] | None = None) -> None:
        self.source_factory = source_factory

    def fetch_yoy(self, *, period_end: datetime) -> float | None:
        source = self.source_factory() if self.source_factory else self._default_source()
        last_day = calendar.monthrange(period_end.year, period_end.month)[1]
        frame = source.tufe(
            start=f"{period_end.year:04d}-{period_end.month:02d}-01",
            end=f"{period_end.year:04d}-{period_end.month:02d}-{last_day:02d}",
        )
        if frame is None or frame.empty:
            return None
        candidates: list[tuple[datetime, float]] = []
        for index, row in frame.iterrows():
            try:
                observed_at = pd.Timestamp(index).to_pydatetime().replace(tzinfo=None)
                value = float(row["YearlyInflation"])
            except (KeyError, TypeError, ValueError):
                continue
            if (
                observed_at.year == period_end.year
                and observed_at.month == period_end.month
                and math.isfinite(value)
            ):
                candidates.append((observed_at, value))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def _default_source() -> Any:
        import borsapy as bp

        return bp.Inflation()
