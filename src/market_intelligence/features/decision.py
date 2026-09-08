from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.features.volatility import WILDER_ATR_14, AtrSeries, wilder_atr_series
from market_intelligence.market_data.bars import CanonicalFrame

DECISION_PANEL_V645 = FeatureSpec(
    feature_id="decision.panel_v645",
    implementation="taramabot_pine_compatible_v645",
    version="6.4.5",
    parameters={
        "minimum_score": 75,
        "pullback_max_rvol": 2.0,
        "pullback_min_pct20": 95.0,
    },
    warmup=WarmupSpec(bars=252, seed="pandas_ewm_adjust_false"),
)


@dataclass(frozen=True)
class DecisionPanelSnapshot:
    score: int
    active_setup: str
    new_setup: str
    entry: bool
    relative_volume: float
    pct20: float
    adx: float
    pullback_guard: bool
    pullback_base: bool


def _frame(source: CanonicalFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": [bar.open for bar in source.bars],
            "high": [bar.high for bar in source.bars],
            "low": [bar.low for bar in source.bars],
            "close": [bar.close for bar in source.bars],
            "volume": [bar.volume for bar in source.bars],
        },
        index=pd.DatetimeIndex([bar.close_time for bar in source.bars]),
    )


def _rma(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    average_gain = _rma(gain, length)
    average_loss = _rma(loss, length)
    relative_strength = average_gain / average_loss.replace(0, np.nan)
    result = 100.0 - 100.0 / (1.0 + relative_strength)
    return result.where(average_loss != 0, 100.0)


def _adx(
    source: pd.DataFrame,
    atr: pd.Series,
    length: int = 14,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    high, low = source["high"], source["low"]
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=source.index)
    minus_dm = pd.Series(
        np.where((down > up) & (down > 0), down, 0.0),
        index=source.index,
    )
    plus_di = 100.0 * _rma(plus_dm, length) / atr.replace(0, np.nan)
    minus_di = 100.0 * _rma(minus_dm, length) / atr.replace(0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return plus_di, minus_di, _rma(dx, length)


def _cross_up(left: pd.Series, right: pd.Series) -> pd.Series:
    return (left > right) & (left.shift(1) <= right.shift(1))


def _fresh(condition: pd.Series) -> pd.Series:
    condition = condition.fillna(False).astype(bool)
    return condition & (~condition.shift(1, fill_value=False))


def decision_v645_frame(
    source: CanonicalFrame,
    atr_values: AtrSeries,
    *,
    minimum_score: int = 75,
) -> pd.DataFrame:
    """Causal port of the frozen taramabot v6.4.5 Pine-compatible decision."""
    data = _frame(source)
    o, h, low, close, volume = (
        data[name] for name in ("open", "high", "low", "close", "volume")
    )
    atr = pd.Series(
        [np.nan if value is None else value for value in atr_values.values],
        index=data.index,
        dtype=float,
    )

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    ema5 = close.ewm(span=5, adjust=False, min_periods=5).mean()
    ema8 = close.ewm(span=8, adjust=False, min_periods=8).mean()
    ema13 = close.ewm(span=13, adjust=False, min_periods=13).mean()
    slope20 = (sma20 / sma20.shift(5) - 1.0) * 100.0
    slope50 = (sma50 / sma50.shift(10) - 1.0) * 100.0
    slope200 = (sma200 / sma200.shift(20) - 1.0) * 100.0

    price_above20 = close > sma20
    sma20_above50 = sma20 > sma50
    sma50_above200 = sma50 > sma200
    slope20_ok = slope20 >= 0.0
    slope50_ok = slope50 >= 0.0
    slope200_ok = slope200 >= -0.5
    trend_core = (
        price_above20
        & sma20_above50
        & sma50_above200
        & slope20_ok
        & slope50_ok
        & slope200_ok
    )

    ema5_up = ema5 > ema5.shift(1)
    ema8_up = ema8 > ema8.shift(1)
    ema13_up = ema13 > ema13.shift(1)
    short_aligned = (ema5 > ema8) & (ema8 > ema13)
    short_slopes = ema5_up & ema8_up & ema13_up
    short_trend = short_aligned & short_slopes
    short_recovery = _cross_up(ema5, ema8) | ((ema5 > ema8) & ema5_up & ema8_up)

    macd = close.ewm(span=12, adjust=False, min_periods=12).mean() - close.ewm(
        span=26, adjust=False, min_periods=26
    ).mean()
    macd_signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    histogram = macd - macd_signal
    macd_above_signal = macd > macd_signal
    macd_above_zero = macd > 0
    hist_positive = histogram > 0
    hist_negative = histogram < 0
    hist_rising = histogram > histogram.shift(1)
    hist_falling = histogram < histogram.shift(1)
    hist_cross_up = hist_positive & (histogram.shift(1) <= 0)
    hist_bull_strengthening = hist_positive & hist_rising
    hist_bull_weakening = hist_positive & hist_falling
    hist_bear_recovering = hist_negative & hist_rising

    rsi = _rsi(close)
    rsi_trend_ok = (rsi >= 55.0) & (rsi <= 72.0)
    rsi_pullback_ok = (rsi >= 50.0) & (rsi <= 72.0)
    rsi_ideal = (rsi >= 55.0) & (rsi <= 68.0)
    plus_di, minus_di, adx = _adx(data, atr)
    strength_core = (adx > 20.0) & (plus_di > minus_di)
    di_ok = plus_di > minus_di
    atr_pct_ok = ((atr / close.replace(0, np.nan) * 100.0) >= 1.5) & (
        (atr / close.replace(0, np.nan) * 100.0) <= 7.0
    )

    average_volume = volume.rolling(10).mean().shift(1)
    rvol = volume / average_volume.replace(0, np.nan)
    turnover = close * volume
    relative_turnover = turnover / turnover.rolling(20).mean().shift(1).replace(0, np.nan)
    high52 = h.rolling(252).max()
    high20 = h.rolling(20).max()
    pct52 = close / high52.replace(0, np.nan) * 100.0
    pct20 = close / high20.replace(0, np.nan) * 100.0
    near52 = pct52 >= 85.0
    near20 = pct20 >= 95.0
    breakout20 = close > high20.shift(1)
    required_rvol = pd.Series(np.where(breakout20, 1.50, 1.20), index=data.index)
    participation_ok = rvol > required_rvol

    distance_pct = (close / sma20.replace(0, np.nan) - 1.0) * 100.0
    distance_atr = (close - sma20) / atr.replace(0, np.nan)
    distance_core = (
        (distance_pct >= 0.0)
        & (distance_pct <= 7.0)
        & (distance_atr >= 0.0)
        & (distance_atr <= 1.50)
    )
    bb_basis = close.rolling(20).mean()
    bb_deviation = 2.0 * close.rolling(20).std(ddof=0)
    bb_width = (2.0 * bb_deviation) / bb_basis.replace(0, np.nan) * 100.0
    bb_width_rising = bb_width > bb_width.shift(1)
    bb_width_above_average = bb_width > bb_width.rolling(20).mean()
    candle_range = (h - low).replace(0, np.nan)
    clv = ((close - low) / candle_range).fillna(0.5)
    upper_wick = h - pd.concat([o, close], axis=1).max(axis=1)
    breakout_quality = bb_width_rising & (clv >= 0.60) & (
        upper_wick / atr.replace(0, np.nan) <= 0.50
    )

    was_above_sma20 = distance_atr.shift(1).rolling(10).max() >= 0.75
    sma20_touched = (low <= sma20 + 0.25 * atr) & (low >= sma20 - 0.50 * atr)
    pullback_base = (
        (~breakout20.fillna(False))
        & was_above_sma20
        & sma20_touched
        & (close > sma20)
        & (distance_atr <= 1.0)
        & ((close > o) | (clv >= 0.60))
    )
    pullback_momentum = (
        macd_above_zero
        & rsi_pullback_ok
        & (hist_bear_recovering | hist_cross_up | hist_bull_strengthening)
    )
    breakout_momentum = (
        macd_above_signal
        & macd_above_zero
        & rsi_trend_ok
        & (hist_bull_strengthening | hist_cross_up)
    )

    trend_score = (
        4 * price_above20.astype(int)
        + 4 * sma20_above50.astype(int)
        + 4 * sma50_above200.astype(int)
        + 3 * slope20_ok.astype(int)
        + 3 * slope50_ok.astype(int)
        + 2 * (slope200 > 0).astype(int)
        + 3 * short_aligned.astype(int)
        + 2 * short_slopes.astype(int)
    )
    histogram_score = pd.Series(
        np.select(
            [hist_cross_up, hist_bull_strengthening, hist_bear_recovering, hist_bull_weakening],
            [6, 6, 4, 2],
            default=0,
        ),
        index=data.index,
    )
    momentum_score = (
        4 * macd_above_zero.astype(int)
        + 5 * macd_above_signal.astype(int)
        + histogram_score
        + 5 * rsi_ideal.astype(int)
    )
    volume_score = pd.Series(
        np.select(
            [rvol >= 3.0, rvol >= 2.0, rvol >= 1.5, rvol >= 1.2, rvol >= 1.0],
            [18, 16, 12, 7, 3],
            default=0,
        ),
        index=data.index,
    ) + 2 * (relative_turnover >= 1.0).astype(int)
    strength_score = pd.Series(
        np.select([adx >= 40, adx >= 30, adx >= 25, adx > 20], [7, 6, 5, 3], default=0),
        index=data.index,
    ) + 3 * di_ok.astype(int)
    location_score = pd.Series(
        np.select([pct52 >= 95, pct52 >= 90, pct52 >= 85], [7, 5, 3], default=0),
        index=data.index,
    ) + 3 * near20.astype(int)
    distance_score = pd.Series(
        np.select(
            [
                (distance_pct >= 0) & (distance_pct <= 3),
                (distance_pct > 3) & (distance_pct <= 5),
                (distance_pct > 5) & (distance_pct <= 7),
            ],
            [5, 4, 2],
            default=0,
        ),
        index=data.index,
    ) + pd.Series(
        np.select(
            [
                (distance_atr >= 0) & (distance_atr < 1.0),
                (distance_atr >= 1.0) & (distance_atr <= 1.5),
                (distance_atr > 1.5) & (distance_atr <= 2.0),
            ],
            [5, 4, 2],
            default=0,
        ),
        index=data.index,
    )
    volatility_score = (
        2 * bb_width_rising.astype(int)
        + bb_width_above_average.astype(int)
        + 2 * atr_pct_ok.astype(int)
    )
    score = (
        trend_score
        + momentum_score
        + volume_score
        + strength_score
        + location_score
        + distance_score
        + volatility_score
    ).astype(int)

    positions = pd.Series(np.arange(len(data)), index=data.index)
    ready = (
        (positions >= 251)
        & sma200.shift(20).notna()
        & rsi.notna()
        & atr.notna()
        & high52.notna()
    )
    structure = trend_core & strength_core & near52
    common = ready & structure & participation_ok & distance_core & (score >= minimum_score)
    breakout = common & breakout20 & short_trend & breakout_momentum & breakout_quality
    pullback_guard = (rvol <= 2.0) & (pct20 >= 95.0)
    pullback = (
        ready
        & structure
        & participation_ok
        & distance_core
        & (score >= minimum_score)
        & pullback_base
        & pullback_momentum
        & (short_recovery | short_trend)
        & pullback_guard.fillna(False)
    )
    trend = (
        common
        & (~breakout20.fillna(False))
        & (~pullback_base.fillna(False))
        & short_trend
        & breakout_momentum
    )
    new_breakout = _fresh(breakout)
    new_pullback = _fresh(pullback)
    new_trend = _fresh(trend)
    active_setup = pd.Series("", index=data.index, dtype=object)
    active_setup.loc[trend] = "TREND DEVAMI"
    active_setup.loc[pullback] = "PULLBACK"
    active_setup.loc[breakout] = "BREAKOUT"
    new_setup = pd.Series("", index=data.index, dtype=object)
    new_setup.loc[new_trend] = "TREND DEVAMI"
    new_setup.loc[new_pullback] = "PULLBACK"
    new_setup.loc[new_breakout] = "BREAKOUT"

    return pd.DataFrame(
        {
            "score": score,
            "rvol": rvol,
            "pct20": pct20,
            "adx": adx,
            "pullback_base": pullback_base.fillna(False),
            "pullback_guard": pullback_guard.fillna(False),
            "breakout": breakout.fillna(False),
            "pullback": pullback.fillna(False),
            "trend": trend.fillna(False),
            "new_breakout": new_breakout,
            "new_pullback": new_pullback,
            "new_trend": new_trend,
            "active_setup": active_setup,
            "new_setup": new_setup,
            "entry": new_setup.ne(""),
        },
        index=data.index,
    )


class DecisionPanelV645Provider:
    spec = DECISION_PANEL_V645
    dependencies = (WILDER_ATR_14,)

    def compute(self, frame: CanonicalFrame) -> DecisionPanelSnapshot | None:
        atr = wilder_atr_series(frame, 14)
        return self._compute(frame, atr)

    def compute_with_dependencies(
        self,
        frame: CanonicalFrame,
        values: dict[str, object],
    ) -> DecisionPanelSnapshot | None:
        atr = values.get(WILDER_ATR_14.feature_id)
        return self._compute(frame, atr if isinstance(atr, AtrSeries) else None)

    def _compute(
        self,
        frame: CanonicalFrame,
        atr: AtrSeries | None,
    ) -> DecisionPanelSnapshot | None:
        if frame.is_partial or len(frame.bars) < self.spec.warmup.bars or atr is None:
            return None
        result = decision_v645_frame(frame, atr)
        if result.empty:
            return None
        row = result.iloc[-1]

        def number(name: str) -> float:
            value = float(row[name])
            return value if np.isfinite(value) else 0.0

        return DecisionPanelSnapshot(
            score=int(row["score"]),
            active_setup=str(row["active_setup"] or ""),
            new_setup=str(row["new_setup"] or ""),
            entry=bool(row["entry"]),
            relative_volume=number("rvol"),
            pct20=number("pct20"),
            adx=number("adx"),
            pullback_guard=bool(row["pullback_guard"]),
            pullback_base=bool(row["pullback_base"]),
        )
