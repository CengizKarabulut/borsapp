from __future__ import annotations

import math
from dataclasses import dataclass

from market_intelligence.features.momentum import recursive_ema
from market_intelligence.features.specs import FeatureSpec, WarmupSpec
from market_intelligence.market_data.bars import CanonicalFrame

TECHNICAL_MARKET_CONTEXT = FeatureSpec(
    feature_id="technical.market_context",
    implementation="market_telegram_suite_context_port_v1",
    version="1.0.0",
    parameters={
        "bb_period": 20,
        "bb_rank_window": 100,
        "adx_period": 14,
        "structure_pivot": 5,
        "profile_lookback": 100,
        "profile_bins": 48,
    },
    warmup=WarmupSpec(bars=60, seed="legacy_recursive"),
)


@dataclass(frozen=True)
class TechnicalMarketContext:
    close: float
    bb_width_percentile: float
    rsi: float
    adx: float
    atr: float
    ema21: float
    ema55: float
    pierced_down: bool
    pierced_up: bool
    stacked_direction: str | None
    squeeze_bars: int
    structure_tone: str
    trend_tone: str
    setup_name: str
    setup_direction: str
    strong_divergences: int
    near_confluence: bool


def _rolling_mean(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    running = 0.0
    for index, value in enumerate(values):
        running += value
        if index >= period:
            running -= values[index - period]
        if index >= period - 1:
            result[index] = running / period
    return result


def _rma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if not values:
        return result
    current = values[0]
    alpha = 1.0 / period
    for index, value in enumerate(values):
        if index:
            current = alpha * value + (1.0 - alpha) * current
        if index >= period - 1:
            result[index] = current
    return result


def _true_ranges(frame: CanonicalFrame) -> list[float]:
    values: list[float] = []
    previous_close: float | None = None
    for bar in frame.bars:
        candidates = [bar.high - bar.low]
        if previous_close is not None:
            candidates.extend((abs(bar.high - previous_close), abs(bar.low - previous_close)))
        values.append(max(candidates))
        previous_close = bar.close
    return values


def _rsi_series(close: list[float], period: int = 14) -> list[float | None]:
    result: list[float | None] = [None] * len(close)
    if len(close) <= period:
        return result
    changes = [current - previous for previous, current in zip(close, close[1:], strict=False)]
    gains = [max(value, 0.0) for value in changes]
    losses = [max(-value, 0.0) for value in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period

    def value() -> float:
        if average_loss == 0:
            return 100.0 if average_gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + average_gain / average_loss)

    result[period] = value()
    for index in range(period, len(changes)):
        average_gain = (average_gain * (period - 1) + gains[index]) / period
        average_loss = (average_loss * (period - 1) + losses[index]) / period
        result[index + 1] = value()
    return result


def _bb_context(close: list[float], period: int = 20, rank_window: int = 100):
    widths: list[float | None] = [None] * len(close)
    for index in range(period - 1, len(close)):
        window = close[index - period + 1 : index + 1]
        mean = sum(window) / period
        variance = sum((value - mean) ** 2 for value in window) / period
        widths[index] = 400.0 * math.sqrt(variance) / mean if mean else None
    ranks: list[float | None] = [None] * len(close)
    minimum = max(10, rank_window // 3)
    for index, current in enumerate(widths):
        if current is None:
            continue
        window = [value for value in widths[max(0, index - rank_window + 1) : index + 1] if value is not None]
        if len(window) >= minimum:
            ranks[index] = sum(value <= current for value in window) / len(window) * 100.0
    streak = 0
    for value in reversed(ranks):
        if value is not None and value <= 25.0:
            streak += 1
        else:
            break
    current_window = close[-period:]
    middle = sum(current_window) / period
    deviation = math.sqrt(sum((value - middle) ** 2 for value in current_window) / period)
    return ranks[-1], streak, middle - 2 * deviation, middle, middle + 2 * deviation


def _adx(frame: CanonicalFrame, period: int = 14) -> tuple[float | None, float | None]:
    ranges = _true_ranges(frame)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for previous, current in zip(frame.bars, frame.bars[1:], strict=False):
        up = current.high - previous.high
        down = previous.low - current.low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
    atr_values = _rma(ranges, period)
    plus_values = _rma(plus_dm, period)
    minus_values = _rma(minus_dm, period)
    dx: list[float] = []
    for atr, plus, minus in zip(atr_values, plus_values, minus_values, strict=True):
        if atr is None or plus is None or minus is None or atr <= 0:
            dx.append(0.0)
            continue
        plus_di = 100.0 * plus / atr
        minus_di = 100.0 * minus / atr
        denominator = plus_di + minus_di
        dx.append(100.0 * abs(plus_di - minus_di) / denominator if denominator else 0.0)
    adx_values = _rma(dx, period)
    return adx_values[-1], atr_values[-1]


def _market_structure(frame: CanonicalFrame, pivot: int = 5):
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for index in range(pivot, len(frame.bars) - pivot):
        window = frame.bars[index - pivot : index + pivot + 1]
        if frame.bars[index].high == max(bar.high for bar in window):
            highs.append((index, frame.bars[index].high))
        if frame.bars[index].low == min(bar.low for bar in window):
            lows.append((index, frame.bars[index].low))
    if len(highs) < 2 or len(lows) < 2:
        return "neutral", None, None
    high_state = "HH" if highs[-1][1] > highs[-2][1] else "LH"
    low_state = "HL" if lows[-1][1] > lows[-2][1] else "LL"
    tone = "positive" if (high_state, low_state) == ("HH", "HL") else "negative" if (high_state, low_state) == ("LH", "LL") else "warning"
    return tone, highs[-1][1], lows[-1][1]


def _profile(frame: CanonicalFrame, lookback: int = 100, bins: int = 48):
    bars = frame.bars[-lookback:]
    low = min(bar.low for bar in bars)
    high = max(bar.high for bar in bars)
    if high <= low:
        return None, None, None
    width = (high - low) / bins
    profile = [0.0] * bins
    for bar in bars:
        first = max(min(int((bar.low - low) / width), bins - 1), 0)
        last = max(min(math.ceil((bar.high - low) / width) - 1, bins - 1), first)
        share = bar.volume / (last - first + 1)
        for index in range(first, last + 1):
            profile[index] += share
    total = sum(profile)
    if total <= 0:
        return None, None, None
    poc_index = max(range(bins), key=profile.__getitem__)
    selected = {poc_index}
    cumulative = profile[poc_index]
    lower, upper = poc_index - 1, poc_index + 1
    while cumulative < total * 0.70 and (lower >= 0 or upper < bins):
        lower_volume = profile[lower] if lower >= 0 else -1.0
        upper_volume = profile[upper] if upper < bins else -1.0
        chosen = upper if upper_volume >= lower_volume else lower
        selected.add(chosen)
        cumulative += profile[chosen]
        if chosen == upper:
            upper += 1
        else:
            lower -= 1
    return (
        low + (poc_index + 0.5) * width,
        low + min(selected) * width,
        low + (max(selected) + 1) * width,
    )


def _failed_break(frame: CanonicalFrame, level: float | None, direction: str) -> bool:
    if level is None:
        return False
    recent = frame.bars[-5:]
    close = recent[-1].close
    if direction == "down":
        return any(bar.low < level for bar in recent) and close > level
    return any(bar.high > level for bar in recent) and close < level


def _pivot_positions(values: list[float | None], *, low: bool, width: int = 5) -> list[int]:
    positions: list[int] = []
    for index in range(width, len(values) - width):
        window = values[index - width : index + width + 1]
        if any(value is None for value in window):
            continue
        numeric = [float(value) for value in window if value is not None]
        center = float(values[index])
        neighbours = numeric[:width] + numeric[width + 1 :]
        if (center < min(neighbours)) if low else (center > max(neighbours)):
            positions.append(index)
    return positions


def _strong_divergences(
    frame: CanonicalFrame,
    oscillator: list[float | None],
    atr: float,
) -> int:
    count = 0
    for low_pivots, bullish in ((_pivot_positions(oscillator, low=True), True), (_pivot_positions(oscillator, low=False), False)):
        for first, second in zip(low_pivots, low_pivots[1:], strict=False):
            if not 5 <= second - first <= 60:
                continue
            age = len(frame.bars) - 1 - (second + 5)
            if not 0 <= age <= 5:
                continue
            first_osc = float(oscillator[first])
            second_osc = float(oscillator[second])
            first_price = frame.bars[first].low if bullish else frame.bars[first].high
            second_price = frame.bars[second].low if bullish else frame.bars[second].high
            regular = (bullish and second_osc > first_osc and second_price < first_price) or (not bullish and second_osc < first_osc and second_price > first_price)
            hidden = (bullish and second_osc < first_osc and second_price > first_price) or (not bullish and second_osc > first_osc and second_price < first_price)
            if not (regular or hidden):
                continue
            points = 1 + int(age <= 2)
            points += int(atr > 0 and abs(second_price - first_price) / atr >= 0.75)
            points += int(abs(second_osc - first_osc) >= 5)
            count += int(points >= 3)
    return count


class TechnicalMarketContextProvider:
    spec = TECHNICAL_MARKET_CONTEXT

    def compute(self, frame: CanonicalFrame) -> TechnicalMarketContext | None:
        if frame.is_partial or len(frame.bars) < self.spec.warmup.bars:
            return None
        close = [bar.close for bar in frame.bars]
        bb_rank, squeeze_bars, bb_lower, bb_mid, bb_upper = _bb_context(close)
        adx, atr = _adx(frame)
        if bb_rank is None or adx is None or atr is None or atr <= 0:
            return None
        ema_periods = [5, 8, 10, 13, 20, 21, 34, 50, 55, 89, 100, 144, 200, 233]
        ema = {period: recursive_ema(close, period) for period in ema_periods if period <= len(close)}
        ema21, ema55 = ema[21][-1], ema[55][-1]
        current = frame.bars[-1]
        prior = frame.bars[-21:-1]
        pierced_down = current.low < min(bar.low for bar in prior) <= current.close
        pierced_up = current.high > max(bar.high for bar in prior) >= current.close
        stacked_direction = "bullish" if current.close > ema21 and current.close > ema55 else "bearish" if current.close < ema21 and current.close < ema55 else None
        structure_tone, swing_high, swing_low = _market_structure(frame)
        values = [ema[period][-1] for period in sorted(ema)]
        bullish_pairs = sum(left > right for left, right in zip(values, values[1:], strict=False))
        bearish_pairs = sum(left < right for left, right in zip(values, values[1:], strict=False))
        pairs = max(len(values) - 1, 1)
        trend_tone = "positive" if bullish_pairs / pairs >= 0.75 else "negative" if bearish_pairs / pairs >= 0.75 else "warning"
        poc, val, vah = _profile(frame)
        failed_down = _failed_break(frame, val, "down") or _failed_break(frame, swing_low, "down")
        failed_up = _failed_break(frame, vah, "up") or _failed_break(frame, swing_high, "up")
        levels = [
            *((value, "EMA") for value in values),
            *((value, "Profil") for value in (poc, val, vah) if value is not None),
            *((value, "Yapı") for value in (swing_high, swing_low) if value is not None),
            (bb_lower, "Volatilite"),
            (bb_mid, "Volatilite"),
            (bb_upper, "Volatilite"),
        ]
        levels.sort()
        clusters: list[list[tuple[float, str]]] = []
        for level in levels:
            if not clusters or level[0] - clusters[-1][0][0] > atr * 0.25:
                clusters.append([level])
            else:
                clusters[-1].append(level)
        near_confluence = any(
            len({family for _, family in cluster}) >= 2
            and abs(sum(value for value, _ in cluster) / len(cluster) - current.close) / atr <= 0.75
            for cluster in clusters
        )
        rsi_series = _rsi_series(close)
        strong_divergences = _strong_divergences(frame, rsi_series, atr)
        setup_name = "Yön arayışı / geçiş"
        setup_direction = "neutral"
        if failed_down and squeeze_bars < 8:
            setup_name, setup_direction = "Destekte reddedilme / başarısız aşağı kırılım", "bullish"
        elif failed_up and squeeze_bars < 8:
            setup_name, setup_direction = "Dirençte reddedilme / başarısız yukarı kırılım", "bearish"
        elif squeeze_bars >= 3 or adx < 18:
            setup_name = "Sıkışma / karar bölgesi"
        elif structure_tone == trend_tone and structure_tone in {"positive", "negative"} and adx >= 20:
            setup_name = "Trend devamı"
            setup_direction = "bullish" if structure_tone == "positive" else "bearish"
        elif strong_divergences and near_confluence and (float(rsi_series[-1]) <= 35 or float(rsi_series[-1]) >= 65):
            setup_name = "Tükenme denemesi"
            setup_direction = "bullish" if float(rsi_series[-1]) <= 35 else "bearish"
        return TechnicalMarketContext(
            close=current.close,
            bb_width_percentile=bb_rank,
            rsi=float(rsi_series[-1]),
            adx=adx,
            atr=atr,
            ema21=ema21,
            ema55=ema55,
            pierced_down=pierced_down,
            pierced_up=pierced_up,
            stacked_direction=stacked_direction,
            squeeze_bars=squeeze_bars,
            structure_tone=structure_tone,
            trend_tone=trend_tone,
            setup_name=setup_name,
            setup_direction=setup_direction,
            strong_divergences=strong_divergences,
            near_confluence=near_confluence,
        )
