"""ATC 2026-10-14 Pine alarm packet's native scanners 1–9.

Source-of-truth is f_native_legacy_snapshot(), NOT the older A-I chart overlay.
The indicator's native packet was ported from the Python reference formulas; same-
feed TradingView numerical parity is not yet verified. Closed canonical bars only.
"""
from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.momentum import (
    LEGACY_RSI_7,
    LEGACY_RSI_14,
    MACD_12_26_9,
    RSI_14,
    SMI_10_3_3,
    MacdSnapshot,
    RsiSnapshot,
    SmiSnapshot,
)
from market_intelligence.features.trend import (
    INCLUSIVE_VOLUME_SMA_10,
    INCLUSIVE_VOLUME_SMA_20,
    LEGACY_TREND_MA_SET,
    InclusiveVolumeSnapshot,
    LegacyTrendMaSnapshot,
)
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext

ATC_SCRIPT_SOURCE = "docs/reference/ATC_TV200_18_TARAMA_20261012.pine"
ATC_SCRIPT_SHA256 = "b2a2fab8e28a369bcd88f66c5f94fd95f1580488e603f3940aa26f3c550776e1"
# Order equals native packet bit positions 1..9, rather than the old chart labels.
ATC_NATIVE_SIGNAL_IDS = (
    "signal.macd_positive_cross",
    "signal.smi_macd_positive",
    "signal.smi_macd_positive_volume_confirmed",
    "signal.ema_trend_volume",
    "signal.rsi_macd_volume",
    "signal.sma_macd_volume",
    "signal.smi_macd_full",
    "signal.smi_macd_early",
    "signal.rsi_momentum_volume",
)

FEATURES = {
    ATC_NATIVE_SIGNAL_IDS[0]: (MACD_12_26_9, RSI_14),
    ATC_NATIVE_SIGNAL_IDS[1]: (SMI_10_3_3, MACD_12_26_9),
    ATC_NATIVE_SIGNAL_IDS[2]: (SMI_10_3_3, MACD_12_26_9, LEGACY_TREND_MA_SET, INCLUSIVE_VOLUME_SMA_20),
    ATC_NATIVE_SIGNAL_IDS[3]: (LEGACY_TREND_MA_SET, INCLUSIVE_VOLUME_SMA_20),
    ATC_NATIVE_SIGNAL_IDS[4]: (LEGACY_RSI_14, MACD_12_26_9, INCLUSIVE_VOLUME_SMA_20),
    ATC_NATIVE_SIGNAL_IDS[5]: (MACD_12_26_9, LEGACY_TREND_MA_SET, INCLUSIVE_VOLUME_SMA_20),
    ATC_NATIVE_SIGNAL_IDS[6]: (SMI_10_3_3, MACD_12_26_9, LEGACY_TREND_MA_SET, INCLUSIVE_VOLUME_SMA_20),
    ATC_NATIVE_SIGNAL_IDS[7]: (SMI_10_3_3, MACD_12_26_9, LEGACY_TREND_MA_SET, INCLUSIVE_VOLUME_SMA_20),
    ATC_NATIVE_SIGNAL_IDS[8]: (LEGACY_RSI_7, INCLUSIVE_VOLUME_SMA_10),
}


@dataclass(frozen=True)
class AtcNativeConfig:
    source_sha256: str = ATC_SCRIPT_SHA256
    source_function: str = "f_native_legacy_snapshot"
    snapshot_bars: int = 600


class AtcNativeSignalScanner:
    family = "signal"
    version = "2.0.0"
    result_kind = ResultKind.EVENT
    supported_timeframes = set(Timeframe)
    accepts_partial_bars = False

    def __init__(self, scanner_id: str):
        if scanner_id not in FEATURES:
            raise ValueError(f"Unknown ATC native scanner: {scanner_id}")
        self.id = scanner_id
        self.rule_number = ATC_NATIVE_SIGNAL_IDS.index(scanner_id) + 1
        self.required_features = FEATURES[scanner_id]

    def _matched(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        values = context.feature_values
        current = frame.bars[-1]
        price = current.close
        volume = current.volume
        macd = values.get(MACD_12_26_9.feature_id)
        smi = values.get(SMI_10_3_3.feature_id)
        trend = values.get(LEGACY_TREND_MA_SET.feature_id)
        vol20 = values.get(INCLUSIVE_VOLUME_SMA_20.feature_id)
        vol10 = values.get(INCLUSIVE_VOLUME_SMA_10.feature_id)
        rsi14 = values.get(RSI_14.feature_id)
        legacy14 = values.get(LEGACY_RSI_14.feature_id)
        legacy7 = values.get(LEGACY_RSI_7.feature_id)

        triggered_macd = isinstance(macd, MacdSnapshot) and (
            (macd.previous_line <= macd.previous_signal and macd.line > macd.signal)
            or (macd.line > macd.signal and macd.line > macd.previous_line)
        )
        triggered_smi = isinstance(smi, SmiSnapshot) and (
            (smi.previous_value <= smi.previous_signal and smi.value > smi.signal)
            or (smi.value > smi.signal and smi.value > smi.previous_value)
        )
        positive_core = (
            triggered_smi and isinstance(smi, SmiSnapshot)
            and isinstance(macd, MacdSnapshot) and smi.value > 0
            and macd.histogram > 0 and macd.histogram > macd.previous_histogram
        )
        negative_core = (
            triggered_smi and isinstance(smi, SmiSnapshot)
            and isinstance(macd, MacdSnapshot) and smi.value < 0
            and macd.histogram < 0 and macd.histogram > macd.previous_histogram
        )
        volume20_high = (
            isinstance(vol20, InclusiveVolumeSnapshot)
            and volume > vol20.mean_volume * 1.5
        )
        volume10_high = (
            isinstance(vol10, InclusiveVolumeSnapshot)
            and volume > vol10.mean_volume * 1.5
        )
        trend_ready = isinstance(trend, LegacyTrendMaSnapshot)
        above200 = trend_ready and price > trend.sma[200]

        if self.rule_number == 1:
            return (
                isinstance(rsi14, RsiSnapshot) and rsi14.value > 30
                and isinstance(macd, MacdSnapshot) and macd.line > 0 and triggered_macd
            )
        if self.rule_number == 2:
            return len(frame.bars) >= 200 and positive_core
        if self.rule_number == 3:
            return positive_core and above200 and volume20_high
        if self.rule_number == 4:
            if not trend_ready:
                return False
            e, prev = trend.ema, trend.previous_ema
            return (
                all(price > e[n] for n in (21, 55, 200))
                and all(
                    (prev[a] <= prev[b] and e[a] > e[b])
                    or (e[a] > e[b] and e[a] > prev[a])
                    for a, b in ((8, 13), (5, 8), (5, 13))
                )
                and volume20_high
            )
        if self.rule_number == 5:
            return (
                isinstance(legacy14, RsiSnapshot) and legacy14.value < 70
                and ((legacy14.previous_value <= 50 and legacy14.value > 50)
                     or (legacy14.value > 50 and legacy14.value > legacy14.previous_value))
                and triggered_macd and volume20_high
            )
        if self.rule_number == 6:
            return (
                trend_ready
                and all(price > trend.sma[n] for n in (5, 8, 21, 50, 55, 200))
                and isinstance(macd, MacdSnapshot) and macd.line > 0
                and triggered_macd and volume20_high
            )
        if self.rule_number == 7:
            return negative_core and above200 and volume20_high
        if self.rule_number == 8:
            return (
                trend_ready and negative_core
                and not (above200 and volume20_high)
            )
        if self.rule_number == 9:
            return (
                len(frame.bars) >= 30 and isinstance(legacy7, RsiSnapshot)
                and legacy7.value > 60
                and ((legacy7.previous_value <= 50 and legacy7.value > 50)
                     or (legacy7.value > 50 and legacy7.value > legacy7.previous_value))
                and volume10_high
            )
        raise AssertionError("Unreachable ATC rule number")

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        return self._matched(frame, context)

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        if not self._matched(frame, context):
            return ()
        return (
            Finding(
                finding_key=f"atc-native-{self.rule_number:02d}",
                instrument_id=frame.instrument_id,
                symbol_at_event=frame.symbol_at_snapshot,
                timeframe=frame.timeframe,
                scanner_id=self.id,
                scanner_version=self.version,
                ruleset_hash=context.ruleset_hash,
                kind=self.result_kind,
                bar_time=context.bar_close_time,
                direction=Direction.BULLISH,
                metrics={
                    "atc_rule_number": self.rule_number,
                    "source": "20261014_pine_native_packet",
                    "source_sha256": ATC_SCRIPT_SHA256,
                    "frame_bars": len(frame.bars),
                },
                evidence=(
                    "ATC güncel Pine f_native_legacy_snapshot A-I alarm paketi.",
                    "Eski Pine grafik A-I hesapları tarama sonucu olarak kullanılmadı.",
                    "Aynı veri akışı üzerinde TradingView/Python paritesi ayrıca test edilecek.",
                ),
            ),
        )
