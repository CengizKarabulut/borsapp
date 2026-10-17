"""Read-only market-data coverage probe of original Pine 631 / live 630 diff."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from market_intelligence.core.timeframes import Timeframe
from market_intelligence.market_data.adapters.borsapy import BorsapyProvider
from market_intelligence.market_data.adapters.tvdatafeed import TvDatafeedBistProvider
from market_intelligence.market_data.adapters.yfinance import YFinanceBistProvider
from market_intelligence.market_data.providers import FetchRequest


def probe(out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    providers = (
        BorsapyProvider(), TvDatafeedBistProvider(),
        YFinanceBistProvider(timestamp_timezone="Europe/Istanbul"),
    )
    now = datetime.now(ZoneInfo("Europe/Istanbul"))
    candidates = ("ISATR", "ISKUR", "UMPAS", "ALTIN", "DMLKT")
    results = {}
    for symbol in candidates:
        sources = {}
        for provider in providers:
            try:
                frame = provider.fetch(FetchRequest(
                    provider_symbol=symbol, timeframe=Timeframe.D1,
                    bars=50, as_of=now,
                ))
                sources[provider.name] = {
                    "valid": bool(frame.bars),
                    "bars": len(frame.bars),
                    "last_closed_source_time": frame.bars[-1].timestamp.isoformat(),
                    "basis": frame.price_basis.value,
                }
            except Exception as exc:
                sources[provider.name] = {
                    "valid": False, "error_type": type(exc).__name__,
                }
        results[symbol] = sources
        print(f"PINNED-DIFF data probe {symbol}: {sources}", flush=True)
    file = out_dir / "ATC_PINE_631_YENI_SEMBOL_VERI_KONTROL.json"
    file.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return results


if __name__ == "__main__":
    probe(Path("runtime_artifacts/pine_631_provider_probe"))
