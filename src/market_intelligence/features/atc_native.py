"""Exact bounded 1–9 alarm-packet arithmetic from the user's Pine v6 source.

Reference: docs/reference/ATC_TV200_18_TARAMA_20261012.pine,
f_native_legacy_snapshot. Do not replace its seeded recurrences with ta.* defaults.
Pine's n=min(requestedBars, bar_index+1), default requestedBars=600.
"""
from __future__ import annotations

from dataclasses import dataclass

from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.market_data.bars import CanonicalFrame

ATC_NATIVE_PACKET = FeatureSpec(
    feature_id="atc.pine.native_packet_1_9",
    implementation="atc_20261017_exact_seeded_bounded_bidirectional_v3",
    version="3.0.0",
    parameters={"requested_bars": 600, "source": "f_native_legacy_snapshot"},
    warmup=WarmupSpec(bars=2, seed="first_close_and_first_delta"),
)


@dataclass(frozen=True)
class NativePacketSnapshot:
    known: tuple[bool, ...]
    flags: tuple[bool, ...]
    long_plan: tuple[float, ...]
    short_plan: tuple[float, ...]
    bars: int
    directions: tuple[int, ...] = ()


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2 / (period + 1)
    state = values[0]
    result = []
    for index, value in enumerate(values):
        if index:
            state = alpha * value + (1 - alpha) * state
        result.append(state)
    return result


def calculate_native_packet(frame: CanonicalFrame, *, requested_bars: int = 600) -> NativePacketSnapshot | None:
    if frame.is_partial or requested_bars < 1:
        return None
    bars = frame.bars[-requested_bars:]
    n = len(bars)
    if n < 2 or any(min(b.open, b.high, b.low, b.close) <= 0 for b in bars):
        return None
    close = [b.close for b in bars]
    high = [b.high for b in bars]
    low = [b.low for b in bars]
    volume = [b.volume for b in bars]
    ema = {p: _ema(close, p) for p in (5, 8, 13, 21, 55, 200)}
    fast, slow = _ema(close, 12), _ema(close, 26)
    macd = [a - b for a, b in zip(fast, slow, strict=True)]
    signal = _ema(macd, 9)
    histogram = [a - b for a, b in zip(macd, signal, strict=True)]

    rsi7: list[float | None] = [None] * n
    rsi14: list[float | None] = [None] * n
    wilder: list[float | None] = [None] * n
    smi: list[float | None] = [None] * n
    smi_signal: list[float | None] = [None] * n
    g7 = l7 = g14 = l14 = 0.0
    wg = wl = gtotal = ltotal = 0.0
    wseed = False
    atr = trtotal = 0.0
    n1 = n2 = d1 = d2 = smi_sig = 0.0
    smi_seed = False

    for i in range(n):
        c, h, low_value = close[i], high[i], low[i]
        if i:
            change = c - close[i - 1]
            gain, loss = max(change, 0.0), max(-change, 0.0)
            if i == 1:
                g7 = g14 = gain
                l7 = l14 = loss
            else:
                g7 = gain / 7 + 6 / 7 * g7
                l7 = loss / 7 + 6 / 7 * l7
                g14 = gain / 14 + 13 / 14 * g14
                l14 = loss / 14 + 13 / 14 * l14
            rsi7[i] = (100.0 if g7 > 0 else None) if l7 == 0 else 100 - 100 / (1 + g7 / l7)
            rsi14[i] = (100.0 if g14 > 0 else None) if l14 == 0 else 100 - 100 / (1 + g14 / l14)
            tr = max(h - low_value, abs(h - close[i - 1]), abs(low_value - close[i - 1]))
            if i <= 14:
                gtotal += gain
                ltotal += loss
                trtotal += tr
            if i == 14:
                wg, wl, atr = gtotal / 14, ltotal / 14, trtotal / 14
                wseed = True
            elif i > 14:
                wg = (13 * wg + gain) / 14
                wl = (13 * wl + loss) / 14
                atr = (13 * atr + tr) / 14
            if wseed:
                wilder[i] = (100.0 if wg > 0 else 50.0) if wl == 0 else 100 - 100 / (1 + wg / wl)
        if i >= 9:
            top, bottom = max(high[i - 9 : i + 1]), min(low[i - 9 : i + 1])
            relative, width = c - (top + bottom) / 2, top - bottom
            if not smi_seed:
                n1 = n2 = relative
                d1 = d2 = width
                smi_seed = True
            else:
                n1 = 0.5 * relative + 0.5 * n1
                n2 = 0.5 * n1 + 0.5 * n2
                d1 = 0.5 * width + 0.5 * d1
                d2 = 0.5 * d1 + 0.5 * d2
            sv = 200 * n2 / (1e-6 if d2 == 0 else d2)
            smi_sig = sv if i == 9 else 0.5 * sv + 0.5 * smi_sig
            smi[i], smi_signal[i] = sv, smi_sig

    smi_ready = n >= 11 and all(v is not None for v in (smi[-1], smi[-2]))
    wilder_ready = n >= 16 and all(v is not None for v in (wilder[-1], wilder[-2]))
    legacy7_ready = n >= 3 and all(v is not None for v in (rsi7[-1], rsi7[-2]))
    legacy14_ready = n >= 3 and all(v is not None for v in (rsi14[-1], rsi14[-2]))
    vol20 = sum(volume[-20:]) / 20 if n >= 20 else None
    vol10 = sum(volume[-10:]) / 10 if n >= 10 else None
    volume20_ready = vol20 is not None and vol20 > 0
    volume10_ready = vol10 is not None and vol10 > 0
    trend = n >= 200
    sma = {p: sum(close[-p:]) / p for p in (5, 8, 21, 50, 55, 200)} if trend else {}
    known = (
        n >= 35 and wilder_ready,
        n >= 35 and smi_ready,
        n >= 35 and smi_ready and trend and volume20_ready,
        trend and volume20_ready,
        n >= 35 and legacy14_ready and volume20_ready,
        n >= 35 and trend and volume20_ready,
        n >= 35 and smi_ready and trend and volume20_ready,
        n >= 35 and smi_ready and trend and volume20_ready,
        legacy7_ready and volume10_ready,
    )
    price = close[-1]
    current_volume = volume[-1]
    macd_trigger = (
        (macd[-2] <= signal[-2] and macd[-1] > signal[-1])
        or (macd[-1] > signal[-1] and macd[-1] > macd[-2])
    )
    smi_trigger = smi_ready and (
        (smi[-2] <= smi_signal[-2] and smi[-1] > smi_signal[-1])
        or (smi[-1] > smi_signal[-1] and smi[-1] > smi[-2])
    )
    positive_core = smi_trigger and smi[-1] > 0 and histogram[-1] > 0 and histogram[-1] > histogram[-2]
    negative_core = smi_trigger and smi[-1] < 0 and histogram[-1] < 0 and histogram[-1] > histogram[-2]
    high20 = volume20_ready and current_volume > vol20 * 1.5
    high10 = volume10_ready and current_volume > vol10 * 1.5
    trend_ema = False
    if trend:
        e5, e8, e13, e21, e55, e200 = (ema[p] for p in (5, 8, 13, 21, 55, 200))
        trend_ema = (
            price > e21[-1] and price > e55[-1] and price > e200[-1]
            and e8[-1] > e13[-1] and e5[-1] > e8[-1] and e5[-1] > e13[-1]
            and (
                (e8[-2] <= e13[-2] and e8[-1] > e13[-1])
                or (e8[-1] > e13[-1] and e8[-1] > e8[-2])
            )
            and (
                (e5[-2] <= e8[-2] and e5[-1] > e8[-1])
                or (e5[-1] > e8[-1] and e5[-1] > e5[-2])
            )
            and (
                (e5[-2] <= e13[-2] and e5[-1] > e13[-1])
                or (e5[-1] > e13[-1] and e5[-1] > e5[-2])
            )
        )
    r14, r14_prev = (wilder[-1], wilder[-2]) if wilder_ready else (0.0, 0.0)
    l14, l14_prev = (rsi14[-1], rsi14[-2]) if legacy14_ready else (0.0, 0.0)
    l7, l7_prev = (rsi7[-1], rsi7[-2]) if legacy7_ready else (0.0, 0.0)
    r14cross = (l14_prev <= 50 < l14) or (l14 > 50 and l14 > l14_prev)
    r7cross = (l7_prev <= 50 < l7) or (l7 > 50 and l7 > l7_prev)
    flags = (
        known[0] and r14 > 30 and macd[-1] > 0 and macd_trigger,
        known[1] and n >= 200 and positive_core,
        known[2] and positive_core and price > sma.get(200, float("inf")) and high20,
        known[3] and trend_ema and high20,
        known[4] and r14cross and l14 < 70 and macd_trigger and high20,
        known[5] and all(price > sma[p] for p in sma) and macd[-1] > 0 and macd_trigger and high20 if trend else False,
        known[6] and negative_core and price > sma.get(200, float("inf")) and high20,
        known[7] and negative_core and not (price > sma.get(200, float("inf")) and high20),
        known[8] and n >= 30 and l7 > 60 and r7cross and high10,
    )
    # Pine 2026-10-17 f_native_legacy_snapshot: bullish flags win any
    # simultaneous bearish flag; evaluate the same nine independent conditions.
    macd_down = (
        (macd[-2] >= signal[-2] and macd[-1] < signal[-1])
        or (macd[-1] < signal[-1] and macd[-1] < macd[-2])
    )
    smi_down = smi_ready and (
        (smi[-2] >= smi_signal[-2] and smi[-1] < smi_signal[-1])
        or (smi[-1] < smi_signal[-1] and smi[-1] < smi[-2])
    )
    bear_core = smi_down and smi[-1] < 0 and histogram[-1] < 0 and histogram[-1] < histogram[-2]
    bear_recovery = smi_down and smi[-1] > 0 and histogram[-1] > 0 and histogram[-1] < histogram[-2]
    ema_down = False
    if trend:
        e5, e8, e13, e21, e55, e200 = (ema[p] for p in (5, 8, 13, 21, 55, 200))
        ema_down = (
            price < e21[-1] and price < e55[-1] and price < e200[-1]
            and (
                (e8[-2] >= e13[-2] and e8[-1] < e13[-1])
                or (e8[-1] < e13[-1] and e8[-1] < e8[-2])
            )
            and (
                (e5[-2] >= e8[-2] and e5[-1] < e8[-1])
                or (e5[-1] < e8[-1] and e5[-1] < e5[-2])
            )
            and (
                (e5[-2] >= e13[-2] and e5[-1] < e13[-1])
                or (e5[-1] < e13[-1] and e5[-1] < e5[-2])
            )
        )
    l14_down = (l14_prev >= 50 > l14) or (l14 < 50 and l14 < l14_prev)
    l7_down = (l7_prev >= 50 > l7) or (l7 < 50 and l7 < l7_prev)
    bear_flags = (
        known[0] and r14 < 70 and macd[-1] < 0 and macd_down,
        known[1] and n >= 200 and bear_core,
        known[2] and bear_core and price < sma.get(200, float("-inf")) and high20,
        known[3] and ema_down and high20,
        known[4] and l14_down and l14 > 30 and macd_down and high20,
        known[5] and all(price < sma[p] for p in sma) and macd[-1] < 0 and macd_down and high20 if trend else False,
        known[6] and bear_recovery and price < sma.get(200, float("-inf")) and high20,
        known[7] and bear_recovery and not (price < sma.get(200, float("-inf")) and high20),
        known[8] and n >= 30 and l7 < 40 and l7_down and high10,
    )
    directions = tuple(1 if bull else -1 if bear else 0 for bull, bear in zip(flags, bear_flags, strict=True))
    flags = tuple(direction != 0 for direction in directions)
    long_plan: tuple[float, ...] = ()
    short_plan: tuple[float, ...] = ()
    if n >= 15 and wseed and atr > 0:
        low7, high7 = min(low[-7:]), max(high[-7:])
        long_risk = max(price - (low7 - 0.2 * atr), 0.75 * atr)
        short_risk = max(high7 + 0.2 * atr - price, 0.75 * atr)
        candidates = (
            (price - long_risk, price + long_risk, price + 2 * long_risk, price + 3 * long_risk),
            (price + short_risk, price - short_risk, price - 2 * short_risk, price - 3 * short_risk),
        )
        if min(candidates[0]) > 0:
            long_plan = candidates[0]
        if min(candidates[1]) > 0:
            short_plan = candidates[1]
    return NativePacketSnapshot(tuple(known), tuple(bool(x) for x in flags), long_plan, short_plan, n, directions)


class AtcNativePacketProvider:
    spec = ATC_NATIVE_PACKET

    def compute(self, frame: CanonicalFrame) -> NativePacketSnapshot | None:
        return calculate_native_packet(frame, requested_bars=int(self.spec.parameters["requested_bars"]))
