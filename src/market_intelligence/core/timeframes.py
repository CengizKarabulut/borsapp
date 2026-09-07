from __future__ import annotations

from enum import StrEnum


class Timeframe(StrEnum):
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    M45 = "45m"
    H1 = "1h"
    H2 = "2h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1wk"
    MO1 = "1mo"

    @property
    def minutes(self) -> int | None:
        return {
            self.M5: 5,
            self.M15: 15,
            self.M30: 30,
            self.M45: 45,
            self.H1: 60,
            self.H2: 120,
            self.H4: 240,
        }.get(self)

    @property
    def is_intraday(self) -> bool:
        return self.minutes is not None


_ALIASES = {
    "5": "5m",
    "15": "15m",
    "30": "30m",
    "45": "45m",
    "60": "1h",
    "60m": "1h",
    "h1": "1h",
    "1h": "1h",
    "2h": "2h",
    "4h": "4h",
    "240": "4h",
    "1d": "1d",
    "d": "1d",
    "daily": "1d",
    "gunluk": "1d",
    "günlük": "1d",
    "1w": "1wk",
    "1wk": "1wk",
    "w": "1wk",
    "weekly": "1wk",
    "haftalik": "1wk",
    "haftalık": "1wk",
    "1m": "1mo",
    "1mo": "1mo",
    "m": "1mo",
    "monthly": "1mo",
    "aylik": "1mo",
    "aylık": "1mo",
}


def parse_timeframe(raw: str) -> Timeframe:
    normalized = raw.strip().casefold()
    return Timeframe(_ALIASES.get(normalized, normalized))
