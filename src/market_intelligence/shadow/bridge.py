from __future__ import annotations

from market_intelligence.market_data.bars import CanonicalFrame


def to_legacy_frame(frame: CanonicalFrame):
    """Return the immutable canonical snapshot in the legacy provider shape.

    Canonical bars are identified by close time, while the frozen legacy
    providers index intraday candles by open time. Preserving that convention
    matters because the technical suite estimates the forming-bar fraction from
    the last index value. Feeding close times would make a fully closed bar
    look newly opened and distort relative-volume screens.
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError('pandas kurulu değil; ".[runtime]" bağımlılıklarını kurun') from exc

    index = pd.DatetimeIndex(
        [bar.open_time for bar in frame.bars],
        name="Datetime",
    ).tz_convert("Europe/Istanbul")
    return pd.DataFrame(
        {
            "Open": [bar.open for bar in frame.bars],
            "High": [bar.high for bar in frame.bars],
            "Low": [bar.low for bar in frame.bars],
            "Close": [bar.close for bar in frame.bars],
            "Volume": [bar.volume for bar in frame.bars],
        },
        index=index,
    )
