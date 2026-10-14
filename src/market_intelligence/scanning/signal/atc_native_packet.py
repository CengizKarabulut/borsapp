"""Scanner adapters for user's unmodified f_native_legacy_snapshot 1–9 flags.

The arithmetic is shared in features/atc_native.py; all nine scans read the
SAME 600-candle bounded native packet, not the old chart overlay conditions.
"""
from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.core.enums import Direction, ResultKind
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.features.atc_native import ATC_NATIVE_PACKET, NativePacketSnapshot
from market_intelligence.market_data.bars import CanonicalFrame
from market_intelligence.scanning.contracts import Finding, ScanContext, ScannerUnavailable

ATC_SCRIPT_SOURCE = "docs/reference/ATC_TV200_18_TARAMA_20261012.pine"
# SHA256 of the exact user-uploaded source bytes (CRLF line endings).
ATC_SCRIPT_SHA256 = "b2a2fab8e28a369bcd88f66c5f94fd95f1580488e603f3940aa26f3c550776e1"
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
    required_features = (ATC_NATIVE_PACKET,)
    accepts_partial_bars = False

    def __init__(self, scanner_id: str):
        if scanner_id not in ATC_NATIVE_SIGNAL_IDS:
            raise ValueError(f"Unknown ATC native scanner: {scanner_id}")
        self.id = scanner_id
        self.rule_number = ATC_NATIVE_SIGNAL_IDS.index(scanner_id) + 1

    def _packet(self, context: ScanContext) -> NativePacketSnapshot:
        packet = context.feature_values.get(ATC_NATIVE_PACKET.feature_id)
        if not isinstance(packet, NativePacketSnapshot):
            raise ScannerUnavailable("Pine native 1–9 packet is missing")
        if not packet.known[self.rule_number - 1]:
            raise ScannerUnavailable(
                f"f_native_legacy_snapshot: rule {self.rule_number} not yet evaluable "
                f"with {packet.bars} bounded candles"
            )
        return packet

    def prefilter(self, frame: CanonicalFrame, context: ScanContext) -> bool:
        return self._packet(context).flags[self.rule_number - 1]

    def evaluate(self, frame: CanonicalFrame, context: ScanContext) -> tuple[Finding, ...]:
        packet = self._packet(context)
        if not packet.flags[self.rule_number - 1]:
            return ()
        plan = {
            "version": "atc-pine-native-20261014",
            "source": ATC_SCRIPT_SOURCE,
            "source_sha256": ATC_SCRIPT_SHA256,
            "status": "unavailable",
            "entry_basis": "confirmed_close_reference",
            "executable_order": False,
            "scenarios": [],
        }
        if packet.long_plan:
            stop, tp1, tp2, tp3 = packet.long_plan
            plan.update(
                status="reference",
                scenarios=[{
                    "side": "long", "entry": frame.bars[-1].close,
                    "stop": stop, "tp1": tp1, "tp2": tp2, "tp3": tp3,
                }],
            )
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
                    "frame_bars": packet.bars,
                    "trade_plan": plan,
                },
                evidence=(
                    "ATC kullanıcı Pine f_native_legacy_snapshot A–I alarm paketi.",
                    "Bütün 1–9 kuralları aynı 600 mumluk fiyat geçmişiyle hesaplandı.",
                    "TradingView/Python aynı-feed bağımsız sayısal eşitlik doğrulaması bekliyor.",
                ),
            ),
        )
