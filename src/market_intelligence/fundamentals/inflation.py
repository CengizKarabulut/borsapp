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


class CpiRebaser:
    """Rebase report-end purchasing power using complete official monthly rates.

    Monthly rates are published rounded: this is a transparent approximation,
    not a replacement for issuer-supplied exact restatement coefficients.
    """
    def __init__(self, archive, source_factory=None):
        self.archive = archive
        self.source_factory = source_factory
        self.memory = {}

    def factor(self, start, end):
        from datetime import UTC
        if start[:7] == end[:7]:
            return 1.0
        if start > end:
            return 1.0 / self.factor(end, start)
        kind = f"factor:{start}:{end}"
        if kind in self.memory:
            return self.memory[kind]
        now = datetime.now(UTC)
        cached = self.archive.latest("CPI", "tcmb", kind, known_at=now)
        if cached is not None:
            self.memory[kind] = cached[2]["factor"]
            return self.memory[kind]
        source = self.source_factory() if self.source_factory else BorsapyTcmbInflationProvider._default_source()
        frame = source.tufe(start=start[:7] + "-01", end=end)
        rates = {}
        for index, row in frame.iterrows():
            period = pd.Timestamp(index).strftime("%Y-%m")
            rate = float(row["MonthlyInflation"])
            if math.isfinite(rate) and rate > -100:
                rates[period] = rate
        first = pd.Period(start, freq="M") + 1
        months = [str(period) for period in pd.period_range(first, pd.Period(end, freq="M"), freq="M")]
        if any(month not in rates for month in months):
            raise ValueError("Incomplete monthly CPI series")
        factor = math.prod(1 + rates[month] / 100 for month in months)
        self.archive.put("CPI", "tcmb", kind, {"factor": factor,
            "monthly_rates": {month: rates[month] for month in months},
            "basis": "compounded_rounded_monthly_CPI", "start": start, "end": end}, observed_at=now)
        self.memory[kind] = factor
        return factor
