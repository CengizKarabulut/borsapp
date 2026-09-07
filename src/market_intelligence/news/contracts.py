from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class NewsItem:
    news_id: str
    source: str
    headline: str
    published_at: datetime
    url: str | None
    symbols: tuple[str, ...] = ()
    summary: str = ""
    provider: str = ""
    category: str = ""
    attachment_count: int = 0
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.news_id.strip():
            raise ValueError("news_id boş olamaz")
        if not self.source.strip():
            raise ValueError("haber kaynağı boş olamaz")
        if not self.headline.strip():
            raise ValueError("haber başlığı boş olamaz")
        if self.published_at.tzinfo is None:
            raise ValueError("haber yayın zamanı timezone-aware olmalıdır")
        if self.attachment_count < 0:
            raise ValueError("ek sayısı negatif olamaz")
