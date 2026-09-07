from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from market_intelligence.features.momentum import recursive_ema
from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.market_data.bars import CanonicalFrame

LEGACY_TREND_MA_SET = FeatureSpec(
    feature_id="trend.ma.legacy_set",
    implementation="legacy_sma_and_recursive_ema_set_v1",
    version="1.0.0",
    parameters={
        "sma_periods": (5, 8, 21, 50, 55, 200),
        "ema_periods": (5, 8, 13, 21, 55, 200),
    },
    warmup=WarmupSpec(bars=200, seed="complete_window"),
)

INCLUSIVE_VOLUME_SMA_20 = FeatureSpec(
    feature_id="volume.sma.inclusive",
    implementation="legacy_current_inclusive_mean_v1",
    version="1.0.0",
    parameters={"period": 20},
    warmup=WarmupSpec(bars=20, seed="complete_window"),
)

INCLUSIVE_VOLUME_SMA_10 = FeatureSpec(
    feature_id="volume.sma.inclusive_10",
    implementation="legacy_current_inclusive_mean_v1",
    version="1.0.0",
    parameters={"period": 10},
    warmup=WarmupSpec(bars=10, seed="complete_window"),
)


@dataclass(frozen=True)
class LegacyTrendMaSnapshot:
    close: float
    sma: Mapping[int, float]
    ema: Mapping[int, float]
    previous_ema: Mapping[int, float]


@dataclass(frozen=True)
class InclusiveVolumeSnapshot:
    observed_volume: float
    mean_volume: float
    ratio: float


class LegacyTrendMaProvider:
    spec = LEGACY_TREND_MA_SET

    def compute(self, frame: CanonicalFrame) -> LegacyTrendMaSnapshot | None:
        sma_periods = tuple(int(value) for value in self.spec.parameters["sma_periods"])
        ema_periods = tuple(int(value) for value in self.spec.parameters["ema_periods"])
        if frame.is_partial or len(frame.bars) < max((*sma_periods, *ema_periods)):
            return None
        close = [bar.close for bar in frame.bars]
        ema_series = {period: recursive_ema(close, period) for period in ema_periods}
        return LegacyTrendMaSnapshot(
            close=frame.bars[-1].close,
            sma={
                period: sum(close[-period:]) / period
                for period in sma_periods
            },
            ema={period: values[-1] for period, values in ema_series.items()},
            previous_ema={period: values[-2] for period, values in ema_series.items()},
        )


class InclusiveVolumeSma20Provider:
    spec = INCLUSIVE_VOLUME_SMA_20

    def compute(self, frame: CanonicalFrame) -> InclusiveVolumeSnapshot | None:
        period = int(self.spec.parameters["period"])
        if frame.is_partial or len(frame.bars) < period:
            return None
        observed = frame.bars[-1].volume
        mean = sum(bar.volume for bar in frame.bars[-period:]) / period
        if mean <= 0:
            return None
        return InclusiveVolumeSnapshot(observed, mean, observed / mean)


class InclusiveVolumeSma10Provider:
    spec = INCLUSIVE_VOLUME_SMA_10

    def compute(self, frame: CanonicalFrame) -> InclusiveVolumeSnapshot | None:
        period = int(self.spec.parameters["period"])
        if frame.is_partial or len(frame.bars) < period:
            return None
        observed = frame.bars[-1].volume
        mean = sum(bar.volume for bar in frame.bars[-period:]) / period
        if mean <= 0:
            return None
        return InclusiveVolumeSnapshot(observed, mean, observed / mean)
