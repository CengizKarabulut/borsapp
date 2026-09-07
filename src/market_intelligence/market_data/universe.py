from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from hashlib import sha256


@dataclass(frozen=True, order=True)
class UniverseMember:
    symbol: str
    provider_symbol: str
    name: str
    market: str = "BIST"
    asset_class: str = "equity"


@dataclass(frozen=True)
class UniverseSyncPlan:
    universe_id: str
    source: str
    as_of: date
    members: tuple[UniverseMember, ...]
    additions: tuple[str, ...]
    removals: tuple[str, ...]
    unchanged_count: int
    content_hash: str

    @property
    def observed_count(self) -> int:
        return len(self.members)

    @property
    def current_count(self) -> int:
        return self.unchanged_count + len(self.removals)

    @property
    def removal_ratio(self) -> float:
        if self.current_count == 0:
            return 0.0
        return len(self.removals) / self.current_count


def build_universe_sync_plan(
    *,
    universe_id: str,
    source: str,
    as_of: date,
    members: tuple[UniverseMember, ...],
    current_symbols: tuple[str, ...],
) -> UniverseSyncPlan:
    normalized: dict[str, UniverseMember] = {}
    for member in members:
        symbol = member.symbol.strip().upper()
        provider_symbol = member.provider_symbol.strip().upper()
        if not symbol or not provider_symbol:
            raise ValueError("Universe sembolü boş olamaz")
        candidate = UniverseMember(
            symbol=symbol,
            provider_symbol=provider_symbol,
            name=member.name.strip() or symbol,
            market=member.market.strip().upper(),
            asset_class=member.asset_class.strip().lower(),
        )
        previous = normalized.get(symbol)
        if previous is not None and previous != candidate:
            raise ValueError(f"Universe kaynağında çelişkili sembol var: {symbol}")
        normalized[symbol] = candidate

    ordered = tuple(normalized[symbol] for symbol in sorted(normalized))
    observed = set(normalized)
    current = {symbol.strip().upper() for symbol in current_symbols}
    additions = tuple(sorted(observed - current))
    removals = tuple(sorted(current - observed))
    payload = [
        {
            "asset_class": item.asset_class,
            "market": item.market,
            "name": item.name,
            "provider_symbol": item.provider_symbol,
            "symbol": item.symbol,
        }
        for item in ordered
    ]
    content_hash = sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return UniverseSyncPlan(
        universe_id=universe_id.strip().upper(),
        source=source,
        as_of=as_of,
        members=ordered,
        additions=additions,
        removals=removals,
        unchanged_count=len(observed & current),
        content_hash=content_hash,
    )


def validate_universe_sync_plan(
    plan: UniverseSyncPlan,
    *,
    minimum_members: int = 300,
    maximum_removal_ratio: float = 0.10,
    allow_large_removal: bool = False,
) -> None:
    if plan.observed_count < minimum_members:
        raise ValueError(
            f"Universe güvenlik freni: kaynak yalnız {plan.observed_count} üye döndürdü; "
            f"beklenen alt sınır {minimum_members}"
        )
    if not 0 <= maximum_removal_ratio <= 1:
        raise ValueError("maximum_removal_ratio 0 ile 1 arasında olmalıdır")
    if plan.removal_ratio > maximum_removal_ratio and not allow_large_removal:
        raise ValueError(
            "Universe güvenlik freni: mevcut üyelerin "
            f"%{plan.removal_ratio * 100:.1f} kadarı listeden çıkarılacaktı; "
            "kaynağı doğruladıktan sonra --allow-large-removal kullanın"
        )
