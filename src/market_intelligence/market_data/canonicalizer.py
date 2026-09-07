from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from market_intelligence.core.identity import stable_hash
from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.market_data.providers import ProviderFrame, TimestampKind
from market_intelligence.scheduling.bist import BistSessionSchedule


class Canonicalizer:
    def __init__(self, schedule: BistSessionSchedule | None = None) -> None:
        self.schedule = schedule or BistSessionSchedule()

    def build(
        self,
        *,
        instrument_id: str,
        symbol_at_snapshot: str,
        market: str,
        provider_frame: ProviderFrame,
        target_timeframe: Timeframe,
        series_revision: int,
    ) -> CanonicalFrame:
        if market != "BIST":
            raise ValueError("İlk canonicalizer dilimi yalnız BIST seansını destekler")
        base = self._base_bars(provider_frame)
        bars = (
            base
            if provider_frame.timeframe is target_timeframe
            else self._resample(base, provider_frame.timeframe, target_timeframe)
        )
        if not bars:
            raise ValueError("Canonicalization sonrası tamamlanmış bar kalmadı")
        identity = {
            "instrument_id": instrument_id,
            "symbol_at_snapshot": symbol_at_snapshot,
            "market": market,
            "timeframe": target_timeframe,
            "series_revision": series_revision,
            "price_basis": provider_frame.price_basis,
            "source": provider_frame.provider,
            "bars": bars,
        }
        snapshot_id = stable_hash(identity)
        return CanonicalFrame(
            instrument_id=instrument_id,
            symbol_at_snapshot=symbol_at_snapshot,
            market=market,
            timeframe=target_timeframe,
            snapshot_id=snapshot_id,
            series_revision=series_revision,
            price_basis=provider_frame.price_basis,
            source=provider_frame.provider,
            bars=bars,
        )

    def _timestamp(self, value: datetime, timezone_name: str) -> datetime:
        source_timezone = ZoneInfo(timezone_name)
        aware = value.replace(tzinfo=source_timezone) if value.tzinfo is None else value
        return aware.astimezone(self.schedule.timezone)

    def _base_bars(self, frame: ProviderFrame) -> tuple[CanonicalBar, ...]:
        raw_bars = frame.bars[:-1] if frame.last_bar_is_partial else frame.bars
        duration_minutes = frame.timeframe.minutes
        result: list[CanonicalBar] = []
        for raw in raw_bars:
            stamp = self._timestamp(raw.timestamp, frame.timestamp_timezone)
            if frame.timeframe is Timeframe.D1:
                opened, closed = self.schedule.session_bounds(stamp.date())
            elif duration_minutes is not None:
                duration = timedelta(minutes=duration_minutes)
                if frame.timestamp_kind is TimestampKind.OPEN:
                    opened, closed = stamp, stamp + duration
                else:
                    opened, closed = stamp - duration, stamp
            else:
                raise ValueError("Haftalık/aylık provider barları takvim adapter'ı gerektirir")
            session_open, session_close = self.schedule.session_bounds(opened.date())
            if opened < session_open or closed > session_close:
                continue
            result.append(
                CanonicalBar(
                    open_time=opened,
                    close_time=closed,
                    open=float(raw.open),
                    high=float(raw.high),
                    low=float(raw.low),
                    close=float(raw.close),
                    volume=float(raw.volume),
                )
            )
        return tuple(sorted(result, key=lambda bar: bar.close_time))

    def _resample(
        self,
        bars: tuple[CanonicalBar, ...],
        source: Timeframe,
        target: Timeframe,
    ) -> tuple[CanonicalBar, ...]:
        source_minutes = source.minutes
        target_minutes = target.minutes
        if source_minutes is None or target_minutes is None:
            raise ValueError("İlk resample dilimi yalnız intraday barları destekler")
        if target_minutes <= source_minutes or target_minutes % source_minutes:
            raise ValueError("Hedef timeframe kaynak timeframe'in tam katı olmalıdır")
        factor = target_minutes // source_minutes
        grouped: dict[tuple[object, datetime], list[CanonicalBar]] = defaultdict(list)
        for bar in bars:
            session_open, session_close = self.schedule.session_bounds(bar.open_time.date())
            elapsed = int((bar.open_time - session_open).total_seconds() // 60)
            if elapsed < 0:
                continue
            bucket_open = session_open + timedelta(
                minutes=(elapsed // target_minutes) * target_minutes
            )
            bucket_close = bucket_open + timedelta(minutes=target_minutes)
            if bucket_close <= session_close:
                grouped[(bar.open_time.date(), bucket_open)].append(bar)

        result: list[CanonicalBar] = []
        for (_session_date, bucket_open), bucket in sorted(
            grouped.items(), key=lambda item: item[0][1]
        ):
            ordered = sorted(bucket, key=lambda bar: bar.open_time)
            bucket_close = bucket_open + timedelta(minutes=target_minutes)
            contiguous = all(
                left.close_time == right.open_time
                for left, right in zip(ordered, ordered[1:], strict=False)
            )
            if (
                len(ordered) != factor
                or ordered[0].open_time != bucket_open
                or ordered[-1].close_time != bucket_close
                or not contiguous
            ):
                continue
            result.append(
                CanonicalBar(
                    open_time=bucket_open,
                    close_time=bucket_close,
                    open=ordered[0].open,
                    high=max(bar.high for bar in ordered),
                    low=min(bar.low for bar in ordered),
                    close=ordered[-1].close,
                    volume=sum(bar.volume for bar in ordered),
                )
            )
        return tuple(result)
