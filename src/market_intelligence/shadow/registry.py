from __future__ import annotations

from market_intelligence.shadow.adapters.ma_live import LegacyMaLiveAdapter
from market_intelligence.shadow.adapters.taramabot_decision import (
    LegacyTaramabotDecisionAdapter,
)
from market_intelligence.shadow.adapters.taramabot_signals import (
    SIGNAL_ALIASES,
    LegacySignalSession,
    LegacyTaramabotSignalAdapter,
)
from market_intelligence.shadow.adapters.technical_suite import (
    TECHNICAL_ALIASES,
    LegacyTechnicalSuiteAdapter,
    LegacyTechnicalSuiteSession,
)
from market_intelligence.shadow.ports import LegacyScannerAdapter


class ShadowAdapterRegistry:
    def __init__(self) -> None:
        technical_session = LegacyTechnicalSuiteSession()
        self._adapters: dict[str, LegacyScannerAdapter] = {
            scanner_id: LegacyTechnicalSuiteAdapter(scanner_id, technical_session)
            for scanner_id in TECHNICAL_ALIASES
        }
        signal_session = LegacySignalSession()
        self._adapters.update(
            {
                scanner_id: LegacyTaramabotSignalAdapter(scanner_id, signal_session)
                for scanner_id in SIGNAL_ALIASES
            }
        )
        decision = LegacyTaramabotDecisionAdapter()
        self._adapters[decision.scanner_id] = decision
        ma_live = LegacyMaLiveAdapter()
        self._adapters[ma_live.scanner_id] = ma_live

    def adapter_for(self, scanner_id: str) -> LegacyScannerAdapter | None:
        return self._adapters.get(scanner_id)


def adapter_for(scanner_id: str) -> LegacyScannerAdapter | None:
    return ShadowAdapterRegistry().adapter_for(scanner_id)


def coverage_report(scanner_ids: tuple[str, ...]) -> tuple[tuple[str, bool], ...]:
    registry = ShadowAdapterRegistry()
    return tuple(
        (scanner_id, registry.adapter_for(scanner_id) is not None)
        for scanner_id in scanner_ids
    )
