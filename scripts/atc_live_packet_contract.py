"""Shared, deterministic file and acknowledgement contract for direction pages."""
from __future__ import annotations

from scripts.atc_live_timeframe_pages import build_timeframe_metadata

VERSION = "atc-unpersisted-latest-candle-v2-direction-groups"
FILES = ("live-snapshot.json", "live-snapshot.csv", "live-snapshot.txt")


def direction_metadata(report):
    return [build_timeframe_metadata(report, minimum_scanners=minimum,
                max_stocks_per_direction=20) for minimum in (1, 2)]


def packet_pages(report):
    expected = direction_metadata(report)
    if report.get("direction_groups") != expected:
        raise ValueError("direction_group_metadata_changed")
    return [page for group in expected for direction in ("bullish", "bearish")
            for page in group["directions"][direction]["pages"]]


def packet_files(report):
    return (*FILES, *(page["filename"] for page in packet_pages(report)))


def acknowledgement_keys(report):
    return ["text", *("photo-" + page["filename"].removesuffix(".png")
                     for page in packet_pages(report)), "csv"]


def verify_acknowledgements(report, receipt):
    expected = acknowledgement_keys(report)
    acks = receipt.get("acknowledged")
    if (receipt.get("packet_version") != VERSION
            or receipt.get("expected_acknowledgements") != expected
            or not isinstance(acks, dict) or set(acks) != set(expected)
            or any(type(value) is not int or value <= 0 for value in acks.values())
            or len(set(acks.values())) != len(acks)):
        raise ValueError("all_direction_page_acknowledgements_required")
