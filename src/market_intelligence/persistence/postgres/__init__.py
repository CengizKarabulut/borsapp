"""PostgreSQL persistence adapters."""

from market_intelligence.persistence.postgres.ma_research import (
    PostgresMaQualificationSource,
)
from market_intelligence.persistence.postgres.outbox import PostgresOutboxRepository
from market_intelligence.persistence.postgres.runtime import (
    PostgresRuntimeRepository,
    RuntimeInstrument,
)
from market_intelligence.persistence.postgres.scan_store import (
    PersistedScan,
    PostgresScanStore,
)
from market_intelligence.persistence.postgres.snapshots import PostgresSnapshotStore
from market_intelligence.persistence.postgres.state_store import (
    PersistedStateRun,
    PostgresStateStore,
)
from market_intelligence.persistence.postgres.symbol_commands import (
    PostgresLongJobQueue,
    PostgresSymbolReadStore,
)
from market_intelligence.persistence.postgres.telegram_updates import (
    PostgresTelegramUpdateRepository,
)

__all__ = [
    "PersistedScan",
    "PersistedStateRun",
    "PostgresOutboxRepository",
    "PostgresRuntimeRepository",
    "PostgresLongJobQueue",
    "PostgresMaQualificationSource",
    "PostgresScanStore",
    "PostgresSnapshotStore",
    "PostgresStateStore",
    "PostgresSymbolReadStore",
    "PostgresTelegramUpdateRepository",
    "RuntimeInstrument",
]
