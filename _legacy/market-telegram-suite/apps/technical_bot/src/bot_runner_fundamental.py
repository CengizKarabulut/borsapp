"""Production router for fundamental and integrated research commands.

The long-running listener and scan/history/watch commands live in
``bot_runner``. This wrapper only owns the richer user-facing research routes,
including the legacy ``/rapor`` alias for the current ``/analiz`` bundle.
"""

from __future__ import annotations

import json
from pathlib import Path

from src import bot_runner as base
from src.fundamental_analysis import build_fundamental_report
from src.fundamental_card import render_fundamental_card
from src.fundamental_quality import apply_coverage_policy
from src.fundamental_telegram import send_fundamental_card
from src.research_pipeline import build_research_bundle
from src.research_telegram import send_research_bundle
from src.research_theme import apply_white_theme
from src.telegram_bot import VALID_TICKER

_BASE_EXECUTE = base.execute

# One visual language for /temel and /analiz. Pine indicator colours are kept;
# only research canvas/panel/text colours are changed to the white theme.
apply_white_theme()


def _validate_ticker(args: list[str], command: str = "temel") -> tuple[str | None, str | None]:
    example = f"/{command} GARAN"
    if not args:
        return None, f"Sembol belirtilmedi. Örnek: {example}"
    ticker = args[0].strip().upper().removesuffix(".IS")
    if not VALID_TICKER.match(ticker):
        return None, f"Geçersiz sembol: {args[0]}. Örnek: {example}"
    if len(args) > 1:
        return None, f"Bu analiz zaman diliminden bağımsızdır. Kullanım: {example}"
    return ticker, None


def handle_fundamental(chat_id: int, args: list[str]) -> None:
    ticker, error = _validate_ticker(args, "temel")
    if error or ticker is None:
        base.reply(chat_id, error or "Geçersiz sembol.")
        return
    base.reply(chat_id, f"{ticker} temel analiz kartı hazırlanıyor…")
    report = apply_coverage_policy(build_fundamental_report(ticker))
    target = base.REPORTS_DIR / "komut" / ticker
    target.mkdir(parents=True, exist_ok=True)
    image = render_fundamental_card(report, target / f"{ticker}_temel.png")
    Path(target / f"{ticker}_temel.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    send_fundamental_card(image, report)


def handle_research(chat_id: int, args: list[str], command: str = "analiz") -> None:
    ticker, error = _validate_ticker(args, command)
    if error or ticker is None:
        base.reply(chat_id, error or "Geçersiz sembol.")
        return

    target = base.REPORTS_DIR / "komut" / ticker
    bundle = build_research_bundle(ticker, target)
    send_research_bundle(
        bundle.summary_card,
        bundle.fundamental_card,
        bundle.financial_card,
        bundle.valuation_peer_card,
        bundle.moving_average_card,
        bundle.technical_chart,
        bundle.report,
    )


def execute(command, intervals: set[str]) -> None:
    if command.name in {"temel", "fundamental", "mali"}:
        handle_fundamental(command.chat_id, command.args)
        return
    if command.name in {"analiz", "arastir", "research", "rapor"}:
        public_command = "rapor" if command.name == "rapor" else "analiz"
        handle_research(command.chat_id, command.args, public_command)
        return
    _BASE_EXECUTE(command, intervals)


def main() -> None:
    base.HELP_TEXT = (
        "Kullanılabilir komutlar:\n"
        "/analiz SEMBOL — temel + bilanço + değerleme + MA + teknik yapı + risk\n"
        "/rapor SEMBOL — /analiz ile aynı güncel araştırma paketi\n"
        "/temel SEMBOL — sektör uyarlamalı temel analiz ve radar kartı\n"
        "/tara [aralık] — yeni tarama başlatır (boşsa saate göre seçilir)\n"
        "/liste — son tamamlanan taramanın tam listesi\n"
        "/gecmis [no] — geçmiş taramalar (numarasız: liste)\n"
        "/takip SEMBOL [aralık] — teyitli yapı seviyelerini izler\n"
        "/takip sil SEMBOL — takipten çıkarır\n"
        "/esik [ad değer] — tarama eşikleri (ör. /esik rvol 2.0)\n"
        "/durum — bot ve tarama durumu\n"
        "/yardim — bu mesaj\n\n"
        "Takip/tarama aralıkları: 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1wk, 1mo\n"
        "Takip uyarıları yalnızca tamamlanmış mum kapanışında değerlendirilir."
    )
    base.execute = execute
    base.main()


if __name__ == "__main__":
    main()
