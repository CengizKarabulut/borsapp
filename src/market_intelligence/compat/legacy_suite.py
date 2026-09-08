from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from market_intelligence.compat.paths import repository_root


def _technical_app() -> Path:
    return repository_root() / "_legacy" / "market-telegram-suite" / "apps" / "technical_bot"


def _chart_app() -> Path:
    return repository_root() / "_legacy" / "market-telegram-suite" / "apps" / "chart_bot"


@contextmanager
def _legacy_imports(app_root: Path, environment: dict[str, str]) -> Iterator[None]:
    if not (app_root / "src" / "__init__.py").is_file():
        raise RuntimeError(f"Legacy uygulama bulunamadı: {app_root}")
    previous = {key: os.environ.get(key) for key in environment}
    previous_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "src" or name.startswith("src.")
    }
    for name in previous_modules:
        sys.modules.pop(name, None)
    sys.path.insert(0, str(app_root))
    os.environ.update(environment)
    try:
        yield
    finally:
        sys.path.remove(str(app_root))
        for name in tuple(sys.modules):
            if name == "src" or name.startswith("src."):
                sys.modules.pop(name, None)
        sys.modules.update(previous_modules)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def generate_and_send_research(
    *,
    symbol: str,
    topic_id: int,
    target: Path,
) -> None:
    with _legacy_imports(
        _technical_app(),
        {
            "TELEGRAM_MESSAGE_THREAD_ID": str(topic_id),
            "MPLBACKEND": "Agg",
        },
    ):
        from src.research_pipeline import build_research_bundle
        from src.research_telegram import send_research_bundle

        bundle = build_research_bundle(symbol, target)
        send_research_bundle(
            bundle.summary_card,
            bundle.fundamental_card,
            bundle.financial_card,
            bundle.valuation_peer_card,
            bundle.moving_average_card,
            bundle.technical_chart,
            bundle.report,
        )


def generate_and_send_fundamental(
    *,
    symbol: str,
    topic_id: int,
    target: Path,
) -> None:
    with _legacy_imports(
        _technical_app(),
        {
            "TELEGRAM_MESSAGE_THREAD_ID": str(topic_id),
            "MPLBACKEND": "Agg",
        },
    ):
        from src.fundamental_analysis import build_fundamental_report
        from src.fundamental_card import render_fundamental_card
        from src.fundamental_quality import apply_coverage_policy
        from src.fundamental_telegram import send_fundamental_card
        from src.research_theme import apply_white_theme

        apply_white_theme()
        target.mkdir(parents=True, exist_ok=True)
        report = apply_coverage_policy(build_fundamental_report(symbol))
        image = render_fundamental_card(report, target / f"{symbol}_temel.png")
        send_fundamental_card(image, report)


def generate_and_send_chart(
    *,
    symbol: str,
    topic_id: int,
    target: Path,
    intervals: tuple[str, ...] = ("1d",),
) -> None:
    with _legacy_imports(
        _chart_app(),
        {
            "TELEGRAM_TOPIC_ID": str(topic_id),
            "BOT_OUTDIR": str(target),
            "MPLBACKEND": "Agg",
        },
    ):
        from src.bot import _render_and_send

        target.mkdir(parents=True, exist_ok=True)
        _render_and_send(symbol, list(intervals), str(topic_id))
