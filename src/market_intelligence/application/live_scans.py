from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, wait
from datetime import timedelta
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe

LABELS = {
    "technical.volume_spike": "Hacim patlaması",
    "technical.squeeze_volume": "Sıkışma + hacim",
    "technical.extreme_rsi": "Uç RSI bölgesi",
    "technical.failed_breakout": "Başarısız kırılım",
    "technical.decision_zone": "Karar bölgesi",
    "technical.trend_continuation": "Trend devamı",
    "technical.exhaustion": "Tükenme",
    "signal.macd_positive_cross": "MACD pozitif",
    "signal.smi_macd_positive": "SMI/MACD momentum",
    "signal.smi_macd_positive_volume_confirmed": "SMI/MACD güçlü onay",
    "signal.rsi_momentum_volume": "RSI momentum/hacim",
    "signal.rsi_macd_volume": "RSI/MACD/hacim",
    "signal.smi_macd_early": "SMI/MACD erken",
    "signal.smi_macd_full": "SMI/MACD tam",
    "signal.sma_macd_volume": "SMA/MACD/hacim",
    "signal.ema_trend_volume": "EMA trend/hacim",
    "ma.near_zone": "MA seviye yakınlığı",
    "decision.panel_v645": "Karar paneli",
}


def bounded_map(executor, function, values, *, pending_limit=2):
    """Only two queued instruments per timeframe: slow lanes cannot monopolize the pool."""
    iterator = iter(values)
    pending = set()
    for _ in range(pending_limit):
        item = next(iterator, None)
        if item is not None:
            pending.add(executor.submit(function, item))
    while pending:
        completed, pending = wait(pending, return_when=FIRST_COMPLETED)
        for future in completed:
            yield future.result()
            item = next(iterator, None)
            if item is not None:
                pending.add(executor.submit(function, item))


def summary_slot(now, calendar):
    local = now.astimezone(ZoneInfo("Europe/Istanbul"))
    if local.date() not in calendar.sessions(local.date(), local.date()):
        return None
    minute = local.hour * 60 + local.minute
    # Closed bars with a 15-minute data allowance; final session summary at 18:30.
    if not 630 <= minute < 1125:
        return None
    return local.replace(minute=local.minute // 15 * 15, second=0, microsecond=0)


def latest_target(planner, timeframe, now):
    due = planner.due(
        timeframe=timeframe, evaluation_time=now - timedelta(minutes=15), watermark=None
    )
    return due[-1] if due else None


SUMMARY_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (e.instrument_id, e.scanner_id)
        e.instrument_id, e.scanner_id, e.symbol_at_evaluation, e.status
    FROM scan_evaluations e JOIN scan_cycles c USING (cycle_id)
    WHERE c.universe_id=%s AND e.timeframe=%s AND e.bar_time=%s AND e.ruleset_hash=ANY(%s)
    ORDER BY e.instrument_id, e.scanner_id, e.evaluated_at DESC, e.evaluation_id DESC
)
SELECT scanner_id, count(*), count(*) FILTER (WHERE status='match'),
       count(*) FILTER (WHERE status='unknown'),
       (array_agg(symbol_at_evaluation ORDER BY symbol_at_evaluation)
           FILTER (WHERE status='match'))[1:10]
FROM latest GROUP BY scanner_id ORDER BY scanner_id
"""


def format_summary(timeframe, target, slot, expected, bindings, rows):
    by_scanner = {row[0]: row[1:] for row in rows}
    lines = [
        f"Tarama özeti · {timeframe.value} · {slot:%d.%m %H:%M}",
        f"Kapanmış mum: {target.astimezone(slot.tzinfo):%d.%m %H:%M}",
        f"Evren: {expected} hisse · 15 dk veri gecikmesi payı",
    ]
    for binding in bindings:
        if timeframe not in binding.shadow_timeframes:
            continue
        identifier = binding.scanner.id
        seen, matches, unknown, symbols = by_scanner.get(identifier, (0, 0, 0, []))
        missing = max(0, expected - seen)
        line = f"{LABELS.get(identifier, identifier)}: {matches} eşleşme"
        if symbols:
            line += " [" + ", ".join(symbols) + (", …" if matches > len(symbols) else "") + "]"
        line += f" · {seen}/{expected} işlendi"
        if unknown:
            line += f" · {unknown} hesaplanamadı"
        if missing:
            line += f" · {missing} bekleyen/erişilemeyen"
        lines.append(line)
    if timeframe is Timeframe.D1:
        lines.append("Günlük sonuçlar kapanıştan sonra yenilenir.")
    return "\n".join(lines)


def split_summary(text, limit=3500):
    parts = []
    current = []
    size = 0
    for line in text.splitlines():
        if size + len(line) + 1 > limit and current:
            parts.append("\n".join(current))
            current, size = [text.splitlines()[0] + " · devam"], len(text.splitlines()[0]) + 9
        current.append(line)
        size += len(line) + 1
    if current:
        parts.append("\n".join(current))
    return tuple(parts)
