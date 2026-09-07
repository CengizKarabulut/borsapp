from __future__ import annotations

import math
from dataclasses import dataclass

from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.market_data.bars import CanonicalFrame

MACD_12_26_9 = FeatureSpec(
    feature_id="momentum.macd",
    implementation="tradingview_recursive_ema_v1",
    version="1.0.0",
    parameters={"fast": 12, "slow": 26, "signal": 9},
    warmup=WarmupSpec(bars=35, seed="first_valid_value"),
)

RSI_14 = FeatureSpec(
    feature_id="momentum.rsi",
    implementation="wilder_sma_seed_v1",
    version="1.0.0",
    parameters={"period": 14},
    warmup=WarmupSpec(bars=15, seed="first_complete_sma"),
)

SMI_10_3_3 = FeatureSpec(
    feature_id="momentum.smi",
    implementation="legacy_pine_double_recursive_ema_v1",
    version="1.0.0",
    parameters={"length_k": 10, "length_d": 3, "signal": 3},
    warmup=WarmupSpec(bars=11, seed="first_valid_value"),
)


@dataclass(frozen=True)
class MacdSnapshot:
    line: float
    signal: float
    histogram: float
    previous_line: float
    previous_signal: float
    previous_histogram: float


@dataclass(frozen=True)
class RsiSnapshot:
    value: float
    previous_value: float


@dataclass(frozen=True)
class SmiSnapshot:
    value: float
    signal: float
    previous_value: float
    previous_signal: float


def recursive_ema(values: list[float], period: int) -> list[float]:
    if period < 1:
        raise ValueError("EMA periyodu pozitif olmalıdır")
    if not values:
        return []
    if not all(math.isfinite(value) for value in values):
        raise ValueError("EMA girdileri sonlu olmalıdır")
    alpha = 2.0 / (period + 1.0)
    result = [values[0]]
    for value in values[1:]:
        result.append(alpha * value + (1.0 - alpha) * result[-1])
    return result


def calculate_macd(frame: CanonicalFrame) -> MacdSnapshot | None:
    close = [bar.close for bar in frame.bars]
    if frame.is_partial or len(close) < MACD_12_26_9.warmup.bars:
        return None
    fast = recursive_ema(close, int(MACD_12_26_9.parameters["fast"]))
    slow = recursive_ema(close, int(MACD_12_26_9.parameters["slow"]))
    line = [fast_value - slow_value for fast_value, slow_value in zip(fast, slow, strict=True)]
    signal = recursive_ema(line, int(MACD_12_26_9.parameters["signal"]))
    histogram = [value - signal_value for value, signal_value in zip(line, signal, strict=True)]
    return MacdSnapshot(
        line=line[-1],
        signal=signal[-1],
        histogram=histogram[-1],
        previous_line=line[-2],
        previous_signal=signal[-2],
        previous_histogram=histogram[-2],
    )


def calculate_rsi(frame: CanonicalFrame, period: int = 14) -> RsiSnapshot | None:
    close = [bar.close for bar in frame.bars]
    if frame.is_partial or len(close) < period + 2:
        return None
    changes = [current - previous for previous, current in zip(close, close[1:], strict=False)]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    values: list[float] = []

    def value() -> float:
        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        ratio = average_gain / average_loss
        return 100.0 - 100.0 / (1.0 + ratio)

    values.append(value())
    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = (average_gain * (period - 1) + gain) / period
        average_loss = (average_loss * (period - 1) + loss) / period
        values.append(value())
    return RsiSnapshot(value=values[-1], previous_value=values[-2])


def calculate_smi(
    frame: CanonicalFrame,
    *,
    length_k: int = 10,
    length_d: int = 3,
    signal_period: int = 3,
) -> SmiSnapshot | None:
    if min(length_k, length_d, signal_period) < 1:
        raise ValueError("SMI periyotları pozitif olmalıdır")
    if frame.is_partial or len(frame.bars) < length_k + 1:
        return None
    relative: list[float] = []
    widths: list[float] = []
    for index in range(length_k - 1, len(frame.bars)):
        window = frame.bars[index - length_k + 1 : index + 1]
        highest = max(bar.high for bar in window)
        lowest = min(bar.low for bar in window)
        relative.append(frame.bars[index].close - (highest + lowest) / 2.0)
        widths.append(highest - lowest)
    numerator = recursive_ema(recursive_ema(relative, length_d), length_d)
    denominator = recursive_ema(recursive_ema(widths, length_d), length_d)
    smi = [
        200.0 * value / (width if width != 0 else 0.000001)
        for value, width in zip(numerator, denominator, strict=True)
    ]
    smi_signal = recursive_ema(smi, signal_period)
    return SmiSnapshot(
        value=smi[-1],
        signal=smi_signal[-1],
        previous_value=smi[-2],
        previous_signal=smi_signal[-2],
    )


class MacdProvider:
    spec = MACD_12_26_9

    def compute(self, frame: CanonicalFrame) -> MacdSnapshot | None:
        return calculate_macd(frame)


class RsiProvider:
    spec = RSI_14

    def compute(self, frame: CanonicalFrame) -> RsiSnapshot | None:
        return calculate_rsi(frame, int(self.spec.parameters["period"]))


class SmiProvider:
    spec = SMI_10_3_3

    def compute(self, frame: CanonicalFrame) -> SmiSnapshot | None:
        return calculate_smi(
            frame,
            length_k=int(self.spec.parameters["length_k"]),
            length_d=int(self.spec.parameters["length_d"]),
            signal_period=int(self.spec.parameters["signal"]),
        )
