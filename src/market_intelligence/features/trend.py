from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.market_data.bars import CanonicalFrame

SMA_200 = FeatureSpec(
    feature_id="trend.sma.close",
    implementation="complete_window_mean_v1",
    version="1.0.0",
    parameters={"period": 200},
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
class MovingAverageSnapshot:
    value: float
    close: float


@dataclass(frozen=True)
class InclusiveVolumeSnapshot:
    observed_volume: float
    mean_volume: float
    ratio: float


class Sma200Provider:
    spec = SMA_200

    def compute(self, frame: CanonicalFrame) -> MovingAverageSnapshot | None:
        period = int(self.spec.parameters["period"])
        if frame.is_partial or len(frame.bars) < period:
            return None
        return MovingAverageSnapshot(
            value=sum(bar.close for bar in frame.bars[-period:]) / period,
            close=frame.bars[-1].close,
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
