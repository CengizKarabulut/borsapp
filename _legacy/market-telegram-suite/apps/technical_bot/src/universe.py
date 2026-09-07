"""BIST sembol evreni.

600+ hisselik tarama için sembol listesini sağlar. Liste borsapy'den alınır ve
diske önbelleklenir; sağlayıcı erişilemezse önbellek, o da yoksa yerel dosya
kullanılır. Böylece tarama tek bir dış çağrıya bağımlı kalmaz.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

CACHE_PATH = Path("reports/bist_universe.json")
CACHE_TTL_SECONDS = 7 * 24 * 3600

# Yatırım fonu, varant, hak kuponu gibi hisse senedi olmayan kayıtlar taramaya
# girmemelidir; teknik yorum bunlar için anlamsızdır.
EXCLUDED_SUFFIXES = ("R", "V", "Y")
EXCLUDED_TICKERS = {"XU100", "XU030", "XBANK"}


@dataclass(frozen=True)
class Universe:
    symbols: list[str]
    source: str
    fetched_at: float

    @property
    def size(self) -> int:
        return len(self.symbols)


def _clean(tickers: list[str]) -> list[str]:
    """Sembolleri normalleştirir ve hisse senedi olmayanları ayıklar."""
    seen: list[str] = []
    for raw in tickers:
        symbol = str(raw).strip().upper().removesuffix(".IS").removesuffix(".E")
        if not symbol or not symbol.isalnum() or len(symbol) < 4 or len(symbol) > 6:
            continue
        if symbol in EXCLUDED_TICKERS or symbol in seen:
            continue
        seen.append(symbol)
    return sorted(seen)


def _read_cache(path: Path, ttl: float) -> Universe | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(payload["fetched_at"]) > ttl:
            return None
        return Universe(list(payload["symbols"]), f"{payload.get('source', 'önbellek')} (önbellek)", float(payload["fetched_at"]))
    except (OSError, ValueError, KeyError):
        return None


def _write_cache(universe: Universe, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"symbols": universe.symbols, "source": universe.source, "fetched_at": universe.fetched_at}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def fetch_from_provider() -> Universe:
    """borsapy üzerinden güncel BIST şirket listesini çeker."""
    import borsapy as bp

    frame = bp.companies()
    if frame is None or frame.empty or "ticker" not in frame:
        raise RuntimeError("borsapy şirket listesi boş döndü.")
    return Universe(_clean(frame["ticker"].tolist()), "borsapy", time.time())


def read_file(path: Path) -> Universe:
    """Yerel dosyadan sembol okur; her satır bir sembol, # yorum satırı."""
    symbols = []
    for line in path.read_text(encoding="utf-8").splitlines():
        candidate = line.split("#", 1)[0].strip()
        if candidate:
            symbols.append(candidate)
    cleaned = _clean(symbols)
    if not cleaned:
        raise ValueError(f"{path} içinde geçerli sembol bulunamadı.")
    return Universe(cleaned, str(path), time.time())


def load_universe(source: str = "auto", watchlist: Path | None = None, cache_path: Path = CACHE_PATH, ttl: float = CACHE_TTL_SECONDS) -> Universe:
    """Tarama evrenini belirler.

    'file' yalnızca yerel listeyi, 'provider' yalnızca borsapy'yi kullanır.
    'auto' önce önbelleğe, sonra sağlayıcıya, en son yerel dosyaya düşer;
    böylece sağlayıcı erişilemediğinde tarama tamamen durmaz.
    """
    if source == "file":
        if watchlist is None:
            raise ValueError("Yerel liste için watchlist yolu gerekir.")
        return read_file(watchlist)
    cached = _read_cache(cache_path, ttl) if source == "auto" else None
    if cached:
        return cached
    try:
        universe = fetch_from_provider()
        _write_cache(universe, cache_path)
        return universe
    except Exception as error:
        if source == "provider":
            raise
        if watchlist is not None and watchlist.exists():
            fallback = read_file(watchlist)
            return Universe(fallback.symbols, f"{watchlist} (sağlayıcı hatası: {type(error).__name__})", time.time())
        raise
