from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TECHNICAL_APP = REPOSITORY_ROOT / "_legacy" / "market-telegram-suite" / "apps" / "technical_bot"
CHART_APP = REPOSITORY_ROOT / "_legacy" / "market-telegram-suite" / "apps" / "chart_bot"


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
        TECHNICAL_APP,
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


def generate_and_send_chart(
    *,
    symbol: str,
    topic_id: int,
    target: Path,
    intervals: tuple[str, ...] = ("1d",),
) -> None:
    with _legacy_imports(
        CHART_APP,
        {
            "TELEGRAM_TOPIC_ID": str(topic_id),
            "BOT_OUTDIR": str(target),
            "MPLBACKEND": "Agg",
        },
    ):
        from src.bot import _render_and_send

        target.mkdir(parents=True, exist_ok=True)
        _render_and_send(symbol, list(intervals), str(topic_id))
