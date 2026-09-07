from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from market_intelligence.market_data.universe import UniverseMember

SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{3,12}$")


class BorsapyBistUniverseProvider:
    """Read the current BIST All Shares (XUTUM) component snapshot."""

    source = "borsapy:XUTUM"
    supported_universe = "BIST_ALL"

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def _borsapy(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import borsapy as bp
        except ImportError as exc:
            raise RuntimeError(
                "borsapy kurulu değil; runtime bağımlılıklarını yükleyin"
            ) from exc
        return bp

    def list_members(self, universe_id: str) -> tuple[UniverseMember, ...]:
        normalized_universe = universe_id.strip().upper()
        if normalized_universe != self.supported_universe:
            raise ValueError(
                f"borsapy universe sağlayıcısı yalnız {self.supported_universe} destekler"
            )
        components = self._borsapy().Index("XUTUM").components
        if not isinstance(components, list):
            raise RuntimeError("borsapy XUTUM bileşenleri liste döndürmedi")

        members: dict[str, UniverseMember] = {}
        rejected: list[str] = []
        for component in components:
            if not isinstance(component, Mapping):
                rejected.append(repr(component))
                continue
            symbol = str(component.get("symbol", "")).strip().upper()
            name = str(component.get("name", symbol)).strip()
            if not SYMBOL_PATTERN.fullmatch(symbol):
                rejected.append(symbol or "<empty>")
                continue
            member = UniverseMember(
                symbol=symbol,
                provider_symbol=symbol,
                name=name or symbol,
            )
            previous = members.get(symbol)
            if previous is not None and previous != member:
                raise RuntimeError(f"borsapy XUTUM içinde çelişkili kayıt: {symbol}")
            members[symbol] = member

        if rejected:
            preview = ", ".join(rejected[:5])
            raise RuntimeError(
                f"borsapy XUTUM içinde {len(rejected)} geçersiz bileşen var: {preview}"
            )
        if not members:
            raise RuntimeError("borsapy XUTUM boş bileşen listesi döndürdü")
        return tuple(members[symbol] for symbol in sorted(members))
