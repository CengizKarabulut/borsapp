from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParityScore:
    scanner_id: str
    timeframe: str
    samples: int
    agree_match: int
    agree_no_match: int
    legacy_only: int
    new_only: int
    finding_diff: int
    unknown: int

    @property
    def comparable(self) -> int:
        return self.samples - self.unknown

    @property
    def agreement(self) -> float:
        if self.comparable <= 0:
            return 0.0
        return (self.agree_match + self.agree_no_match) / self.comparable

    def passes(
        self,
        *,
        minimum_samples: int = 200,
        minimum_agreement: float = 0.995,
    ) -> bool:
        return (
            self.samples >= minimum_samples
            and self.agreement >= minimum_agreement
            and self.legacy_only == 0
        )
