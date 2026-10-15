"""Thread-safe durable vendor/symbol/timeframe cooldowns for GitHub scans.

A failed provider is retried after 45m, 90m, 180m ... up to 24h. The table
lives in PostgreSQL, not on the ephemeral Actions runner. Reads are prefetched
once per Python process. Fail-open if the cooldown store itself is unavailable:
market data correctness remains the provider's responsibility.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from functools import lru_cache
from threading import RLock

READ_SQL = """
SELECT provider, provider_symbol, timeframe, next_retry_at
FROM provider_retry_cooldowns WHERE next_retry_at > now()
"""
FAIL_SQL = """
INSERT INTO provider_retry_cooldowns
    (provider, provider_symbol, timeframe, failures, next_retry_at, last_error)
VALUES (%s, %s, %s, 1, now() + interval '45 minutes', %s)
ON CONFLICT (provider, provider_symbol, timeframe)
DO UPDATE SET failures = LEAST(8, provider_retry_cooldowns.failures + 1),
              next_retry_at = now() + make_interval(
                  mins => LEAST(
                      1440, 45 * power(2, LEAST(5, provider_retry_cooldowns.failures))
                  )::integer
              ),
              last_error = EXCLUDED.last_error,
              updated_at = now()
RETURNING next_retry_at
"""
CLEAR_SQL = """
DELETE FROM provider_retry_cooldowns
WHERE provider = %s AND provider_symbol = %s AND timeframe = %s
"""


class ProviderRetryCooldowns:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._lock = RLock()
        self._loaded = False
        self._active: dict[tuple[str, str, str], datetime] = {}

    @staticmethod
    def _key(provider: str, symbol: str, timeframe: str) -> tuple[str, str, str]:
        return (provider, symbol.upper().strip(), timeframe)

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.database_url:
            return
        try:
            import psycopg

            with psycopg.connect(self.database_url, autocommit=True) as db:
                with db.cursor() as cursor:
                    cursor.execute(READ_SQL)
                    self._active = {
                        self._key(p, s, tf): until
                        for p, s, tf, until in cursor.fetchall()
                    }
        except Exception as exc:
            print(f"Cooldown read unavailable: {type(exc).__name__}", file=sys.stderr)

    def skip(self, provider: str, symbol: str, timeframe: str) -> bool:
        with self._lock:
            self._load()
            until = self._active.get(self._key(provider, symbol, timeframe))
            return until is not None and until > datetime.now(UTC)

    def failed(self, provider: str, symbol: str, timeframe: str, error: str) -> None:
        if not self.database_url:
            return
        key = self._key(provider, symbol, timeframe)
        try:
            import psycopg

            with psycopg.connect(self.database_url, autocommit=True) as db:
                with db.cursor() as cursor:
                    cursor.execute(FAIL_SQL, (*key, error[:120]))
                    until = cursor.fetchone()[0]
            with self._lock:
                self._active[key] = until
        except Exception as exc:
            print(f"Cooldown update unavailable: {type(exc).__name__}", file=sys.stderr)

    def recovered(self, provider: str, symbol: str, timeframe: str) -> None:
        key = self._key(provider, symbol, timeframe)
        with self._lock:
            if key not in self._active:
                return
        if not self.database_url:
            return
        try:
            import psycopg

            with psycopg.connect(self.database_url, autocommit=True) as db:
                with db.cursor() as cursor:
                    cursor.execute(CLEAR_SQL, key)
            with self._lock:
                self._active.pop(key, None)
        except Exception as exc:
            print(f"Cooldown recovery unavailable: {type(exc).__name__}", file=sys.stderr)


@lru_cache(maxsize=2)
def cooldowns_for(database_url: str) -> ProviderRetryCooldowns:
    return ProviderRetryCooldowns(database_url)
