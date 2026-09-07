from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.decision_context import relative_strength_context
from src.stock_dashboard import (
    ScanConfig,
    calculate_indicators,
    download_benchmark,
    download_prices,
)
from src.telegram_client import send_text

DEFAULT_CHAT_ID = "-1003502567927"


def read_watchlist(path: Path) -> list[str]:
    symbols = []
    for line in path.read_text(encoding="utf-8").splitlines():
        symbol = line.split("#", 1)[0].strip().upper()
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    if not symbols:
        raise ValueError("Watchlist boş; her satıra bir BIST sembolü yazın.")
    return symbols


def evaluate_conditions(data, rs: dict[str, Any], bb_rank_max: float, rvol_min: float) -> dict[str, Any]:
    row = data.iloc[-1]
    rvol = float(row["Volume"] / data["Volume"].shift(1).rolling(20).mean().iloc[-1])
    bb_rank = float(row["BB_WIDTH_RANK"])
    squeeze_rvol = bb_rank <= bb_rank_max and rvol >= rvol_min
    return {
        "matched": squeeze_rvol,
        "condition": "BB_SQUEEZE_RVOL",
        "bb_width_percentile": bb_rank,
        "rvol": rvol,
        "relative_strength": rs.get("state", "Benchmark verisi yok"),
        "close": float(row["Close"]),
    }


def telegram_text(matches: list[dict[str, Any]], scanned: int) -> str:
    lines = ["🔎 BIST Watchlist Durum Alarmı", f"Taranan: {scanned} | Eşleşen: {len(matches)}", ""]
    for item in matches:
        lines.append(
            f"• {item['ticker']} | Fiyat {item['close']:.2f} | BB perc %{item['bb_width_percentile']:.0f} "
            f"| RVOL {item['rvol']:.2f}x | {item['relative_strength']}"
        )
    lines.extend(["", "Koşul: Bollinger genişlik yüzdeliği düşük + RVOL yüksek.", "Durum alarmıdır; AL/SAT sinyali değildir."])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Watchlist üzerinde tarafsız teknik durum koşulları tarar.")
    parser.add_argument("--watchlist", default="watchlist.txt")
    parser.add_argument("--period", default="2y")
    parser.add_argument("--provider", default="AUTO", choices=["AUTO", "BORSAPY", "YFINANCE"])
    parser.add_argument("--bb-rank-max", type=float, default=20.0)
    parser.add_argument("--rvol-min", type=float, default=1.5)
    parser.add_argument("--output", default="reports/watchlist_scan.json")
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()

    tickers = read_watchlist(Path(args.watchlist))
    benchmark_config = ScanConfig("XU100", market="BIST", period=args.period, provider=args.provider)
    benchmark_symbol, benchmark = download_benchmark(benchmark_config)
    results = []
    for ticker in tickers:
        try:
            config = ScanConfig(ticker, market="BIST", period=args.period, provider=args.provider)
            symbol, prices = download_prices(config)
            data = calculate_indicators(prices)
            rs = relative_strength_context(data, benchmark, benchmark_symbol)
            item = evaluate_conditions(data, rs, args.bb_rank_max, args.rvol_min)
            item.update({"ticker": ticker, "symbol": symbol, "error": None})
        except Exception as exc:  # noqa: BLE001 -- isolate one failed watchlist symbol
            item = {"ticker": ticker, "matched": False, "error": str(exc)}
        results.append(item)

    matches = [item for item in results if item.get("matched")]
    payload = {
        "condition": {"name": "BB_SQUEEZE_RVOL", "bb_rank_max": args.bb_rank_max, "rvol_min": args.rvol_min},
        "scanned": len(results),
        "matched": len(matches),
        "results": results,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Watchlist tarandı: {len(results)} sembol, {len(matches)} eşleşme. JSON: {output}")
    if args.send_telegram and matches:
        send_text(telegram_text(matches, len(results)))
        print("Eşleşmeler Telegram'a gönderildi.")


if __name__ == "__main__":
    main()
