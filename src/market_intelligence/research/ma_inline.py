"""Optional SAME-FRAME MA qualification for ATC Rule 18.

Never invent MA levels. Historical support/resistance qualifications are
computed from the identical confirmed canonical OHLCV snapshot being scanned.
The production default continues using saved, versioned PostgreSQL research;
the fallback is opt-in until full-runtime benchmarking succeeds.
"""
from __future__ import annotations

from market_intelligence.features.ma import MaQualification
from market_intelligence.research.ma_levels import MaResearchConfig, research_ma_levels


class ExactFrameMaQualificationSource:
    """Use persisted MA research when available; recompute only when absent."""

    def __init__(self, primary, *, config: MaResearchConfig | None = None):
        self.primary = primary
        self.config = config or MaResearchConfig()

    def load(self, frame):
        prior = self.primary.load(frame)
        if prior:
            return prior
        if frame.is_partial or len(frame.bars) < max(420, max(self.config.periods) + 22):
            return ()
        researched = research_ma_levels(frame, self.config)
        # Include genuinely examined but nonqualified candidates to establish
        # known/NO_MATCH rather than incorrectly reporting unavailable.
        return tuple(
            MaQualification(
                ma_type=level.ma_type,
                period=level.period,
                level_class=level.level_class,
                touches=level.touches,
                quality_score=level.quality_score,
                research_version=level.research_version,
                qualification_side=level.qualification_side,
            )
            for level in researched
        )
