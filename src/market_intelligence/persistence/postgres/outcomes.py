from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from market_intelligence.core.enums import Direction, PriceBasis
from market_intelligence.core.timeframes import parse_timeframe
from market_intelligence.market_data.bars import CanonicalBar, CanonicalFrame
from market_intelligence.persistence.postgres.scan_store import PostgresConnection
from market_intelligence.research.outcomes import Outcome


@dataclass(frozen=True)
class OutcomeCandidate:
    event_id: str
    instrument_id: str
    symbol: str
    scanner_id: str
    timeframe: str
    event_bar_time: datetime
    direction: Direction
    source: str
    price_basis: PriceBasis
    series_revision: int


@dataclass(frozen=True)
class OutcomeReportRow:
    scanner_id: str
    timeframe: str
    horizon_bars: int
    samples: int
    average_raw_return: float
    average_excess_return: float | None
    win_rate: float
    average_mfe: float
    average_mae: float


LIST_CANDIDATES_SQL = """
SELECT event.event_id, event.instrument_id, event.symbol_at_event,
       event.scanner_id, event.timeframe, event.bar_time, event.direction,
       snapshot.source, snapshot.price_basis, snapshot.series_revision
FROM scan_events event
JOIN scan_evaluations evaluation ON evaluation.evaluation_id = event.evaluation_id
JOIN data_snapshots snapshot ON snapshot.snapshot_id = evaluation.snapshot_id
WHERE event.bar_time >= %s
  AND (%s IS NULL OR event.scanner_id = %s)
ORDER BY event.bar_time, event.event_id
"""

LOAD_BARS_SQL = """
SELECT open_time, close_time, open, high, low, close, volume
FROM canonical_market_bars
WHERE instrument_id = %s AND timeframe = %s AND source = %s
  AND price_basis = %s AND series_revision = %s AND close_time >= %s
ORDER BY close_time
LIMIT %s
"""

LOAD_BENCHMARK_BARS_SQL = """
SELECT bar.open_time, bar.close_time, bar.open, bar.high, bar.low, bar.close, bar.volume,
       bar.instrument_id, bar.series_revision
FROM instrument_symbols symbol
JOIN canonical_market_bars bar ON bar.instrument_id = symbol.instrument_id
WHERE symbol.provider = 'canonical' AND upper(symbol.symbol) = 'XU100'
  AND symbol.valid_from <= %s::date
  AND (symbol.valid_to IS NULL OR symbol.valid_to >= %s::date)
  AND bar.timeframe = %s AND bar.source = %s AND bar.price_basis = %s
  AND bar.series_revision = (
      SELECT max(candidate.series_revision)
      FROM canonical_market_bars candidate
      WHERE candidate.instrument_id = bar.instrument_id
        AND candidate.timeframe = bar.timeframe
        AND candidate.source = bar.source
        AND candidate.price_basis = bar.price_basis
  )
  AND bar.close_time >= %s
ORDER BY bar.close_time
LIMIT %s
"""

UPSERT_OUTCOME_SQL = """
INSERT INTO finding_outcomes (
    event_id, horizon_bars, observed_at, raw_return, benchmark_return,
    excess_return, max_favorable_excursion, max_adverse_excursion,
    price_basis, methodology_version
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (event_id, horizon_bars, methodology_version) DO UPDATE SET
    observed_at = EXCLUDED.observed_at,
    raw_return = EXCLUDED.raw_return,
    benchmark_return = EXCLUDED.benchmark_return,
    excess_return = EXCLUDED.excess_return,
    max_favorable_excursion = EXCLUDED.max_favorable_excursion,
    max_adverse_excursion = EXCLUDED.max_adverse_excursion,
    price_basis = EXCLUDED.price_basis
"""

REPORT_SQL = """
SELECT event.scanner_id, event.timeframe, outcome.horizon_bars,
       count(*) AS samples,
       avg(outcome.raw_return), avg(outcome.excess_return),
       avg(CASE WHEN outcome.raw_return > 0 THEN 1.0 ELSE 0.0 END),
       avg(outcome.max_favorable_excursion), avg(outcome.max_adverse_excursion)
FROM finding_outcomes outcome
JOIN scan_events event ON event.event_id = outcome.event_id
WHERE outcome.observed_at >= %s
GROUP BY event.scanner_id, event.timeframe, outcome.horizon_bars
HAVING count(*) >= %s
ORDER BY event.scanner_id, event.timeframe, outcome.horizon_bars
"""


class PostgresOutcomeStore:
    def __init__(self, connection: PostgresConnection) -> None:
        self.connection = connection

    def candidates(
        self,
        *,
        since: datetime,
        scanner_id: str | None = None,
    ) -> tuple[OutcomeCandidate, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(LIST_CANDIDATES_SQL, (since, scanner_id, scanner_id))
            rows = cursor.fetchall()
        return tuple(
            OutcomeCandidate(
                event_id=str(row[0]),
                instrument_id=str(row[1]),
                symbol=str(row[2]),
                scanner_id=str(row[3]),
                timeframe=str(row[4]),
                event_bar_time=row[5],
                direction=Direction(str(row[6])),
                source=str(row[7]),
                price_basis=PriceBasis(str(row[8])),
                series_revision=int(row[9]),
            )
            for row in rows
        )

    @staticmethod
    def _bars(rows) -> tuple[CanonicalBar, ...]:
        return tuple(
            CanonicalBar(
                open_time=row[0],
                close_time=row[1],
                open=float(row[2]),
                high=float(row[3]),
                low=float(row[4]),
                close=float(row[5]),
                volume=float(row[6]),
            )
            for row in rows
        )

    def load_frame(
        self,
        candidate: OutcomeCandidate,
        *,
        maximum_horizon: int,
    ) -> CanonicalFrame | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                LOAD_BARS_SQL,
                (
                    candidate.instrument_id,
                    candidate.timeframe,
                    candidate.source,
                    candidate.price_basis.value,
                    candidate.series_revision,
                    candidate.event_bar_time,
                    maximum_horizon + 1,
                ),
            )
            rows = cursor.fetchall()
        bars = self._bars(rows)
        if not bars or bars[0].close_time != candidate.event_bar_time:
            return None
        return CanonicalFrame(
            instrument_id=candidate.instrument_id,
            symbol_at_snapshot=candidate.symbol,
            market="BIST",
            timeframe=parse_timeframe(candidate.timeframe),
            snapshot_id=f"outcome:{candidate.event_id}",
            series_revision=candidate.series_revision,
            price_basis=candidate.price_basis,
            source=candidate.source,
            bars=bars,
        )

    def load_benchmark(
        self,
        candidate: OutcomeCandidate,
        *,
        maximum_horizon: int,
    ) -> CanonicalFrame | None:
        with self.connection.cursor() as cursor:
            cursor.execute(
                LOAD_BENCHMARK_BARS_SQL,
                (
                    candidate.event_bar_time,
                    candidate.event_bar_time,
                    candidate.timeframe,
                    candidate.source,
                    candidate.price_basis.value,
                    candidate.event_bar_time,
                    maximum_horizon + 1,
                ),
            )
            rows = cursor.fetchall()
        if not rows:
            return None
        bars = self._bars(rows)
        if bars[0].close_time != candidate.event_bar_time:
            return None
        return CanonicalFrame(
            instrument_id=str(rows[0][7]),
            symbol_at_snapshot="XU100",
            market="BIST",
            timeframe=parse_timeframe(candidate.timeframe),
            snapshot_id=f"outcome-benchmark:{candidate.event_id}",
            series_revision=int(rows[0][8]),
            price_basis=candidate.price_basis,
            source=candidate.source,
            bars=bars,
        )

    def save(self, outcomes: tuple[Outcome, ...], *, observed_at: datetime) -> int:
        complete = tuple(outcome for outcome in outcomes if outcome.complete)
        if not complete:
            return 0
        with self.connection.transaction():
            with self.connection.cursor() as cursor:
                for outcome in complete:
                    cursor.execute(
                        UPSERT_OUTCOME_SQL,
                        (
                            outcome.event_id,
                            outcome.horizon_bars,
                            observed_at,
                            outcome.raw_return,
                            outcome.benchmark_return,
                            outcome.excess_return,
                            outcome.max_favorable_excursion,
                            outcome.max_adverse_excursion,
                            outcome.price_basis.value,
                            outcome.methodology_version,
                        ),
                    )
        return len(complete)

    def report(self, *, since: datetime, minimum_samples: int) -> tuple[OutcomeReportRow, ...]:
        with self.connection.cursor() as cursor:
            cursor.execute(REPORT_SQL, (since, minimum_samples))
            rows = cursor.fetchall()
        return tuple(
            OutcomeReportRow(
                scanner_id=str(row[0]),
                timeframe=str(row[1]),
                horizon_bars=int(row[2]),
                samples=int(row[3]),
                average_raw_return=float(row[4]),
                average_excess_return=float(row[5]) if row[5] is not None else None,
                win_rate=float(row[6]),
                average_mfe=float(row[7]),
                average_mae=float(row[8]),
            )
            for row in rows
        )
