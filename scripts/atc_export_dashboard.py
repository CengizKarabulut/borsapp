#!/usr/bin/env python3
"""Read-only borsapp PostgreSQL -> ATC Excel/Power BI scan matrix.

A MATCH without stored directional evidence is NOT called bullish. No Telegram sends.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.persistence.postgres.runtime import PostgresRuntimeRepository
from market_intelligence.scanning.display_codes import SCANNER_ORDER
from market_intelligence.scanning.catalog import load_scanner_catalog
from market_intelligence.scheduling.xist import ExchangeCalendarsXist

TIMEFRAMES = ('5m', '15m', '1h', '4h', '1d', '1wk')
COLUMNS = ('Hisse', 'ZamanDilimi', 'TaramaNo', 'MotorKimligi', 'Durum',
           'MumKapanisiUTC', 'MotorSurumu', 'KuralHash', 'HataKodu', 'VeriKaynagi')

# Read only completed cycles. Match directions must belong to the same evaluation.
LATEST_SQL = """
SELECT DISTINCT ON (e.instrument_id, e.timeframe, e.scanner_id)
    e.instrument_id, e.timeframe, e.scanner_id, e.scanner_version,
    e.ruleset_hash, e.bar_time, e.status, e.error_code, e.evaluation_id,
    ARRAY(
        SELECT DISTINCT evidence.direction
        FROM (
            SELECT ev.direction AS direction FROM scan_events ev
            WHERE ev.evaluation_id = e.evaluation_id
            UNION ALL
            SELECT st.metrics ->> '_atc_direction' AS direction FROM active_states st
            WHERE st.instrument_id = e.instrument_id
              AND st.scanner_id = e.scanner_id
              AND st.timeframe = e.timeframe
              AND st.producer_version = e.scanner_version
              AND st.ruleset_hash = e.ruleset_hash
              AND st.last_seen_at = e.bar_time
              AND st.status = 'active'
        ) evidence WHERE evidence.direction IS NOT NULL
        ORDER BY evidence.direction
    )
FROM scan_evaluations e
JOIN scan_cycles c ON c.cycle_id = e.cycle_id
WHERE c.universe_id = %s AND e.instrument_id = ANY(%s::uuid[])
  AND c.status IN ('completed', 'completed_with_errors')
ORDER BY e.instrument_id, e.timeframe, e.scanner_id,
         e.bar_time DESC, e.evaluated_at DESC, e.evaluation_id DESC
"""


def status_label(status: str, directions: tuple[str, ...] | list[str]) -> str:
    """Fail closed: neither unknown nor missing direction may become a signal."""
    if status == 'unknown':
        return 'HESAPLANAMADI'
    if status == 'no_match':
        return 'KOSUL_YOK'
    if status != 'match':
        return 'HESAPLANAMADI'
    d = set(directions)
    if not d or not d.issubset({'bullish', 'bearish', 'neutral', 'mixed'}):
        return 'ESLESME_YON_BELIRSIZ'
    if 'mixed' in d or ('bullish' in d and 'bearish' in d):
        return 'KARMA'
    if d == {'bullish'}:
        return 'POZITIF'
    if d == {'bearish'}:
        return 'NEGATIF'
    if d == {'neutral'}:
        return 'NOTR'
    return 'KARMA'


def matrix_rows(members, evaluations, bindings, *, timeframes=TIMEFRAMES):
    """Create complete universe coverage and distinguish NO_DATA from NO_MATCH."""
    if len(set(SCANNER_ORDER)) != 18 or set(bindings) != set(SCANNER_ORDER):
        raise ValueError('18 tarama kataloğunda kaynak/kural uyumsuzluğu')
    unique = {(str(i), s.upper()): (str(i), s.upper()) for i, s in members}
    symbols = [symbol for _, symbol in unique.values()]
    if len(symbols) != len(set(symbols)):
        raise ValueError('Bir hisse farklı instrument_id ile birden çok kez geldi')
    known = {}
    for ev in evaluations:
        instrument_id, tf, scanner_id = str(ev[0]), str(ev[1]), str(ev[2])
        key = (instrument_id, tf, scanner_id)
        if key in known:
            raise ValueError(f'En son değerlendirmede mükerrer kayıt: {key}')
        known[key] = ev
    for instrument_id, symbol in sorted(unique.values(), key=lambda x: x[1]):
        for tf in timeframes:
            for number, scanner_id in enumerate(SCANNER_ORDER, 1):
                binding = bindings[scanner_id]
                ev = known.get((instrument_id, tf, scanner_id))
                row = {column: '' for column in COLUMNS}
                row.update(Hisse=symbol, ZamanDilimi=tf, TaramaNo=number,
                           MotorKimligi=scanner_id)
                if tf not in {x.value for x in binding.shadow_timeframes}:
                    row['Durum'] = 'DESTEKLENMIYOR'
                elif ev is None:
                    row['Durum'] = 'VERI_YOK'
                else:
                    _, _, _, version, rule_hash, bar_time, status, error_code, _, directions = ev
                    row.update(MumKapanisiUTC=bar_time.astimezone(UTC).isoformat(), MotorSurumu=version,
                               KuralHash=rule_hash, HataKodu=error_code or '',
                               VeriKaynagi='borsapp:scan_evaluations')
                    if version != binding.scanner.version or rule_hash != binding.ruleset_hash:
                        row['Durum'] = 'SURUM_UYUSMAZLIGI'
                    else:
                        row['Durum'] = status_label(status, directions or ())
                yield row


def export_matrix(db, universe, config_path, destination, *, as_of: date, require_members: int = 0):
    bindings_tuple = load_scanner_catalog(
        Path(config_path), calendar_version=ExchangeCalendarsXist().version
    )
    bindings = {binding.scanner.id: binding for binding in bindings_tuple}
    members = PostgresRuntimeRepository(db).list_universe(universe, as_of=as_of)
    if not members:
        raise ValueError(f'Evren boş: {universe}; universe-sync çalıştırın')
    if require_members and len(members) < require_members:
        raise ValueError(
            f'ATC kapsam eksik: BIST evreni {len(members)} hisse; hedef {require_members}. '
            'Eksik sembolleri doğrulamadan 630 hisse raporu üretilemez.'
        )
    member_pairs = [(member.instrument_id, member.symbol) for member in members]
    with db.cursor() as cursor:
        cursor.execute(LATEST_SQL, (universe, [member.instrument_id for member in members]))
        evaluations = cursor.fetchall()
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    temporary = destination.with_suffix(destination.suffix + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=COLUMNS)
            writer.writeheader()
            for row in matrix_rows(member_pairs, evaluations, bindings):
                counts[row['Durum']] = counts.get(row['Durum'], 0) + 1
                writer.writerow(row)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {'universe': universe, 'as_of': as_of.isoformat(), 'members': len(members),
            'conditions': 18, 'timeframes': len(TIMEFRAMES), 'statuses': counts,
            'csv': str(destination)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', default='BIST_ALL')
    parser.add_argument('--as-of', type=date.fromisoformat, default=datetime.now(ZoneInfo('Europe/Istanbul')).date())
    parser.add_argument('--config', default='config/scanners.toml')
    parser.add_argument('--output', default='runtime_artifacts/ATC_Tarama_Matris.csv')
    parser.add_argument('--require-members', type=int, default=0,
                        help='Kapsam bu sayıdan azsa sessiz eksik rapor yerine hata ver')
    args = parser.parse_args()
    database_url = os.getenv('DATABASE_URL')
    if not database_url:
        parser.error('DATABASE_URL ayarlanmalı; kimlik bilgilerini repoya koymayın')
    import psycopg
    with psycopg.connect(database_url) as db:
        result = export_matrix(db, args.universe, args.config, args.output,
                               as_of=args.as_of, require_members=args.require_members)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
