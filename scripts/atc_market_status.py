"""Dated official exchange notices, separate from source failures or price data."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "config/atc_market_events.json"


def load_market_events(path=DEFAULT_PATH):
    document = json.loads(Path(path).read_bytes())
    if document.get("schema") != "atc-official-market-events-v1" or not isinstance(document.get("events"), list):
        raise ValueError("official_market_event_schema_invalid")
    rows = []
    for event in document["events"]:
        if not isinstance(event, dict) or event.get("status") != "official_halt":
            raise ValueError("official_market_event_status_invalid")
        if not re.fullmatch(r"[A-Z0-9.]{2,16}", event.get("symbol", "")):
            raise ValueError("official_market_event_symbol_invalid")
        first, last, resume = (date.fromisoformat(event[key]) for key in
                               ("from_session", "through_session", "resume_session"))
        published = datetime.fromisoformat(event["published_at"])
        source = urlsplit(event["source_url"])
        if (last < first or resume <= last or published.utcoffset() is None
                or source.scheme != "https" or source.hostname not in {"www.kap.org.tr", "kap.org.tr"}
                or not re.fullmatch(r"/tr/Bildirim/\d+", source.path)
                or source.query or source.fragment or source.username is not None
                or source.password is not None or source.port is not None):
            raise ValueError("official_market_event_provenance_invalid")
        if any(previous["symbol"] == event["symbol"]
               and first <= date.fromisoformat(previous["through_session"])
               and last >= date.fromisoformat(previous["from_session"]) for previous in rows):
            raise ValueError("official_market_event_windows_overlap")
        rows.append(dict(event))
    return rows


def market_event_for(symbol, session, *, observed_at, events=None):
    if not isinstance(session, date) or isinstance(session, datetime) or observed_at.utcoffset() is None:
        raise ValueError("dated_market_event_observation_required")
    for event in load_market_events() if events is None else events:
        if (event["symbol"] == symbol
                and date.fromisoformat(event["from_session"]) <= session <= date.fromisoformat(event["through_session"])
                and datetime.fromisoformat(event["published_at"]) <= observed_at):
            return dict(event)
    return None
