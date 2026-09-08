from __future__ import annotations

import math
from dataclasses import dataclass, field

from market_intelligence.features.decision import DECISION_PANEL_V645, DecisionPanelSnapshot
from market_intelligence.features.momentum import (
    MACD_12_26_9,
    RSI_14,
    SMI_10_3_3,
    MacdSnapshot,
    RsiSnapshot,
    SmiSnapshot,
)
from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.features.technical import (
    TECHNICAL_MARKET_CONTEXT,
    TechnicalMarketContext,
)
from market_intelligence.features.volatility import WILDER_ATR_14, AtrSeries
from market_intelligence.market_data.bars import CanonicalFrame

RESEARCH_TECHNICAL_SNAPSHOT = FeatureSpec(
    feature_id="research.technical_snapshot",
    implementation="borsapp_point_in_time_research_v1",
    version="1.0.0",
    parameters={
        "support_resistance_lookback": 120,
        "fibonacci_lookback": 60,
        "volatility_period": 20,
        "volume_period": 20,
    },
    warmup=WarmupSpec(bars=252, seed="dependency_specs"),
)


@dataclass(frozen=True)
class ResearchTechnicalSnapshot:
    close: float
    previous_close: float
    change_pct: float
    period_returns: dict[str, float | None]
    high_52w: float
    low_52w: float
    distance_to_high_pct: float
    distance_to_low_pct: float
    sma20: float
    sma50: float
    sma200: float
    rsi14: float
    macd_line: float
    macd_signal: float
    macd_histogram: float
    atr14: float
    atr_pct: float
    annualized_volatility_20d: float | None
    average_volume_20d: float
    relative_volume_20d: float
    cmf20: float | None
    obv_bias: str
    support_levels: tuple[float, ...]
    resistance_levels: tuple[float, ...]
    fibonacci_levels: dict[str, float]
    candlestick_patterns: tuple[str, ...]
    structure_tone: str
    trend_tone: str
    setup_name: str
    setup_direction: str
    bb_width_percentile: float
    adx14: float
    decision_score: int
    active_setup: str
    decision_entry: bool
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    daily_volume: float = 0.0
    turnover: float = 0.0
    moving_averages: dict[int, float] = field(default_factory=dict)
    moving_average_slopes: dict[int, float | None] = field(default_factory=dict)
    smi: float | None = None
    smi_signal: float | None = None
    plus_di: float | None = None
    minus_di: float | None = None
    profile_poc: float | None = None
    profile_val: float | None = None
    profile_vah: float | None = None
    vwap20: float | None = None
    anchored_vwap: float | None = None
    swing_high: float | None = None
    swing_low: float | None = None
    high_label: str = "—"
    low_label: str = "—"
    strong_divergences: int = 0
    near_confluence: bool = False
    bb_lower: float | None = None
    bb_middle: float | None = None
    bb_upper: float | None = None


def _return(close: list[float], bars: int) -> float | None:
    if len(close) <= bars or close[-bars - 1] == 0:
        return None
    return (close[-1] / close[-bars - 1] - 1.0) * 100.0


def _historical_volatility(close: list[float], period: int) -> float | None:
    if len(close) <= period:
        return None
    returns = [
        math.log(current / previous)
        for previous, current in zip(close[-period - 1 : -1], close[-period:], strict=True)
        if previous > 0 and current > 0
    ]
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252.0) * 100.0


def _support_resistance(
    frame: CanonicalFrame,
    lookback: int = 120,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    bars = frame.bars[-lookback:]
    width = 3
    lows: list[float] = []
    highs: list[float] = []
    for index in range(width, len(bars) - width):
        window = bars[index - width : index + width + 1]
        if bars[index].low == min(item.low for item in window):
            lows.append(bars[index].low)
        if bars[index].high == max(item.high for item in window):
            highs.append(bars[index].high)
    close = bars[-1].close

    def distinct(values: list[float], *, below: bool) -> tuple[float, ...]:
        selected: list[float] = []
        candidates = sorted(
            (value for value in values if (value < close) is below),
            reverse=below,
        )
        for value in candidates:
            if all(abs(value - other) / close > 0.01 for other in selected):
                selected.append(value)
            if len(selected) == 3:
                break
        return tuple(selected)

    return distinct(lows, below=True), distinct(highs, below=False)


def _money_flow(frame: CanonicalFrame, period: int = 20) -> float | None:
    bars = frame.bars[-period:]
    volume = sum(bar.volume for bar in bars)
    if volume <= 0:
        return None
    flow = 0.0
    for bar in bars:
        spread = bar.high - bar.low
        multiplier = (
            ((bar.close - bar.low) - (bar.high - bar.close)) / spread
            if spread
            else 0.0
        )
        flow += multiplier * bar.volume
    return flow / volume


def _obv_bias(frame: CanonicalFrame, period: int = 20) -> str:
    bars = frame.bars[-period - 1 :]
    obv = 0.0
    first_half = 0.0
    for index, (previous, current) in enumerate(zip(bars, bars[1:], strict=False), 1):
        if current.close > previous.close:
            obv += current.volume
        elif current.close < previous.close:
            obv -= current.volume
        if index == period // 2:
            first_half = obv
    delta = obv - first_half
    return "positive" if delta > 0 else "negative" if delta < 0 else "neutral"


def _patterns(frame: CanonicalFrame) -> tuple[str, ...]:
    previous, current = frame.bars[-2], frame.bars[-1]
    body = abs(current.close - current.open)
    spread = max(current.high - current.low, 1e-12)
    lower_wick = min(current.open, current.close) - current.low
    upper_wick = current.high - max(current.open, current.close)
    patterns: list[str] = []
    if body / spread <= 0.1:
        patterns.append("Doji")
    if lower_wick >= body * 2 and upper_wick <= max(body, spread * 0.1):
        patterns.append("Çekiç benzeri mum")
    if (
        current.close > current.open
        and previous.close < previous.open
        and current.open <= previous.close
        and current.close >= previous.open
    ):
        patterns.append("Boğa yutan mum")
    if (
        current.close < current.open
        and previous.close > previous.open
        and current.open >= previous.close
        and current.close <= previous.open
    ):
        patterns.append("Ayı yutan mum")
    return tuple(patterns)


class ResearchTechnicalSnapshotProvider:
    spec = RESEARCH_TECHNICAL_SNAPSHOT
    dependencies = (
        WILDER_ATR_14,
        RSI_14,
        MACD_12_26_9,
        SMI_10_3_3,
        TECHNICAL_MARKET_CONTEXT,
        DECISION_PANEL_V645,
    )

    def compute_with_dependencies(
        self,
        frame: CanonicalFrame,
        values: dict[str, object],
    ) -> ResearchTechnicalSnapshot | None:
        if frame.is_partial or len(frame.bars) < self.spec.warmup.bars:
            return None
        atr = values.get(WILDER_ATR_14.feature_id)
        rsi = values.get(RSI_14.feature_id)
        macd = values.get(MACD_12_26_9.feature_id)
        smi = values.get(SMI_10_3_3.feature_id)
        context = values.get(TECHNICAL_MARKET_CONTEXT.feature_id)
        decision = values.get(DECISION_PANEL_V645.feature_id)
        if not isinstance(atr, AtrSeries) or not isinstance(rsi, RsiSnapshot):
            return None
        if not isinstance(macd, MacdSnapshot) or not isinstance(context, TechnicalMarketContext):
            return None
        if not isinstance(smi, SmiSnapshot):
            return None
        if not isinstance(decision, DecisionPanelSnapshot):
            return None
        close = [bar.close for bar in frame.bars]
        volume = [bar.volume for bar in frame.bars]
        latest = close[-1]
        high_52w = max(bar.high for bar in frame.bars[-252:])
        low_52w = min(bar.low for bar in frame.bars[-252:])
        average_volume = sum(volume[-20:]) / 20.0
        support, resistance = _support_resistance(frame)
        swing = frame.bars[-60:]
        swing_high = max(bar.high for bar in swing)
        swing_low = min(bar.low for bar in swing)
        distance = swing_high - swing_low
        periods = (5, 8, 13, 20, 50, 100, 200)
        moving_averages = {
            period: sum(close[-period:]) / period
            for period in periods
        }
        moving_average_slopes: dict[int, float | None] = {}
        for period in periods:
            previous_window = close[-period - 5 : -5]
            previous_average = sum(previous_window) / period if len(previous_window) == period else None
            moving_average_slopes[period] = (
                (moving_averages[period] / previous_average - 1.0) * 100.0
                if previous_average
                else None
            )
        recent = frame.bars[-20:]
        recent_volume = sum(bar.volume for bar in recent)
        vwap20 = (
            sum(((bar.high + bar.low + bar.close) / 3.0) * bar.volume for bar in recent)
            / recent_volume
            if recent_volume > 0
            else None
        )
        anchor_index = min(range(max(0, len(frame.bars) - 120), len(frame.bars)), key=lambda index: frame.bars[index].low)
        anchored = frame.bars[anchor_index:]
        anchored_volume = sum(bar.volume for bar in anchored)
        anchored_vwap = (
            sum(((bar.high + bar.low + bar.close) / 3.0) * bar.volume for bar in anchored)
            / anchored_volume
            if anchored_volume > 0
            else None
        )
        fibonacci = {
            "0.0%": swing_low,
            "23.6%": swing_high - distance * 0.236,
            "38.2%": swing_high - distance * 0.382,
            "50.0%": swing_high - distance * 0.5,
            "61.8%": swing_high - distance * 0.618,
            "78.6%": swing_high - distance * 0.786,
            "100.0%": swing_high,
        }
        return ResearchTechnicalSnapshot(
            close=latest,
            previous_close=close[-2],
            change_pct=(latest / close[-2] - 1.0) * 100.0,
            period_returns={
                "1 hafta": _return(close, 5),
                "1 ay": _return(close, 21),
                "3 ay": _return(close, 63),
                "6 ay": _return(close, 126),
                "1 yıl": _return(close, 251),
            },
            high_52w=high_52w,
            low_52w=low_52w,
            distance_to_high_pct=(latest / high_52w - 1.0) * 100.0,
            distance_to_low_pct=(latest / low_52w - 1.0) * 100.0,
            sma20=sum(close[-20:]) / 20.0,
            sma50=sum(close[-50:]) / 50.0,
            sma200=sum(close[-200:]) / 200.0,
            rsi14=rsi.value,
            macd_line=macd.line,
            macd_signal=macd.signal,
            macd_histogram=macd.histogram,
            atr14=atr.latest,
            atr_pct=atr.latest / latest * 100.0,
            annualized_volatility_20d=_historical_volatility(close, 20),
            average_volume_20d=average_volume,
            relative_volume_20d=volume[-1] / average_volume if average_volume else 0.0,
            cmf20=_money_flow(frame),
            obv_bias=_obv_bias(frame),
            support_levels=support,
            resistance_levels=resistance,
            fibonacci_levels=fibonacci,
            candlestick_patterns=_patterns(frame),
            structure_tone=context.structure_tone,
            trend_tone=context.trend_tone,
            setup_name=context.setup_name,
            setup_direction=context.setup_direction,
            bb_width_percentile=context.bb_width_percentile,
            adx14=context.adx,
            decision_score=decision.score,
            active_setup=decision.active_setup,
            decision_entry=decision.entry,
            open=frame.bars[-1].open,
            high=frame.bars[-1].high,
            low=frame.bars[-1].low,
            daily_volume=frame.bars[-1].volume,
            turnover=frame.bars[-1].volume * latest,
            moving_averages=moving_averages,
            moving_average_slopes=moving_average_slopes,
            smi=smi.value,
            smi_signal=smi.signal,
            plus_di=context.plus_di,
            minus_di=context.minus_di,
            profile_poc=context.profile_poc,
            profile_val=context.profile_val,
            profile_vah=context.profile_vah,
            vwap20=vwap20,
            anchored_vwap=anchored_vwap,
            swing_high=context.swing_high,
            swing_low=context.swing_low,
            high_label=context.high_label,
            low_label=context.low_label,
            strong_divergences=context.strong_divergences,
            near_confluence=context.near_confluence,
            bb_lower=context.bb_lower,
            bb_middle=context.bb_middle,
            bb_upper=context.bb_upper,
        )
