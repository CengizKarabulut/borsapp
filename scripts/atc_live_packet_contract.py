"""Shared, deterministic file and acknowledgement contract for direction pages."""
from __future__ import annotations

from scripts.atc_live_timeframe_pages import build_timeframe_metadata

LEGACY_VERSION = "atc-unpersisted-latest-candle-v2-direction-groups"
VERSION = "atc-unpersisted-latest-candle-v3-bist-long-only"
READABLE_VERSIONS = frozenset({LEGACY_VERSION, VERSION})
FILES = ("live-snapshot.json", "live-snapshot.csv", "live-snapshot.txt")


def notification_policy():
    """Return a fresh policy; analytical SHORT evidence remains in report/CSV."""
    return {"id": "bist-long-only-v1", "market": "BIST",
            "notification_directions": ["bullish"],
            "analytical_directions": ["bullish", "bearish"]}


def notification_directions(report):
    version = report.get("version")
    if version == VERSION:
        if report.get("notification_policy") != notification_policy():
            raise ValueError("bist_notification_policy_changed")
        return ("bullish",)
    if version == LEGACY_VERSION and "notification_policy" not in report:
        return ("bullish", "bearish")
    raise ValueError("unsupported_direction_packet_version")


def direction_metadata(report):
    return [build_timeframe_metadata(report, minimum_scanners=minimum,
                max_stocks_per_direction=20,
                allowed_directions=notification_directions(report)) for minimum in (1, 2)]


def packet_pages(report):
    expected = direction_metadata(report)
    if report.get("direction_groups") != expected:
        raise ValueError("direction_group_metadata_changed")
    return [page for group in expected for direction in notification_directions(report)
            for page in group["directions"][direction]["pages"]]


def packet_files(report):
    return (*FILES, *(page["filename"] for page in packet_pages(report)))


def acknowledgement_keys(report):
    return ["text", *("photo-" + page["filename"].removesuffix(".png")
                     for page in packet_pages(report)), "csv"]


def verify_acknowledgements(report, receipt):
    expected = acknowledgement_keys(report)
    acks = receipt.get("acknowledged")
    if (receipt.get("packet_version") != report.get("version")
            or report.get("version") == VERSION
                and receipt.get("notification_policy") != notification_policy()
            or receipt.get("expected_acknowledgements") != expected
            or not isinstance(acks, dict) or set(acks) != set(expected)
            or any(type(value) is not int or value <= 0 for value in acks.values())
            or len(set(acks.values())) != len(acks)):
        raise ValueError("all_direction_page_acknowledgements_required")
