from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class WatermarkPlanner:
    """Return every closed bar after the persisted watermark up to evaluation time."""

    def due(
        self,
        *,
        closed_bar_times: tuple[datetime, ...],
        evaluation_time: datetime,
        watermark: datetime | None,
    ) -> tuple[datetime, ...]:
        if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
            raise ValueError("evaluation_time timezone bilgisi içermelidir")
        if watermark is not None and (
            watermark.tzinfo is None or watermark.utcoffset() is None
        ):
            raise ValueError("watermark timezone bilgisi içermelidir")
        return tuple(
            bar_time
            for bar_time in sorted(set(closed_bar_times))
            if bar_time <= evaluation_time
            and (watermark is None or bar_time > watermark)
        )
