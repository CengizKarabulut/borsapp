from __future__ import annotations

import unittest
from datetime import date

from market_intelligence.market_data.adapters.borsapy_universe import (
    BorsapyBistUniverseProvider,
)
from market_intelligence.market_data.universe import (
    UniverseMember,
    build_universe_sync_plan,
    validate_universe_sync_plan,
)


class FakeIndex:
    components = [
        {"symbol": "THYAO", "name": "Türk Hava Yolları"},
        {"symbol": "ASELS", "name": "Aselsan"},
    ]


class FakeBorsapy:
    @staticmethod
    def Index(symbol: str) -> FakeIndex:
        if symbol != "XUTUM":
            raise AssertionError(symbol)
        return FakeIndex()


class UniverseProviderTests(unittest.TestCase):
    def test_xutum_components_become_sorted_bist_members(self) -> None:
        members = BorsapyBistUniverseProvider(FakeBorsapy()).list_members("bist_all")
        self.assertEqual([member.symbol for member in members], ["ASELS", "THYAO"])
        self.assertEqual(members[0].provider_symbol, "ASELS")
        self.assertEqual(members[0].market, "BIST")

    def test_invalid_component_fails_closed(self) -> None:
        class InvalidIndex:
            components = [{"symbol": "BAD.E", "name": "Bad"}]

        class InvalidBorsapy:
            @staticmethod
            def Index(_symbol: str) -> InvalidIndex:
                return InvalidIndex()

        with self.assertRaisesRegex(RuntimeError, "geçersiz"):
            BorsapyBistUniverseProvider(InvalidBorsapy()).list_members("BIST_ALL")


class UniversePlanTests(unittest.TestCase):
    def test_plan_is_deterministic_and_reports_changes(self) -> None:
        plan = build_universe_sync_plan(
            universe_id="bist_all",
            source="test:XUTUM",
            as_of=date(2026, 9, 7),
            members=(
                UniverseMember("THYAO", "THYAO", "Türk Hava Yolları"),
                UniverseMember("ASELS", "ASELS", "Aselsan"),
            ),
            current_symbols=("ASELS", "EREGL"),
        )
        self.assertEqual(plan.universe_id, "BIST_ALL")
        self.assertEqual(plan.additions, ("THYAO",))
        self.assertEqual(plan.removals, ("EREGL",))
        self.assertEqual(plan.unchanged_count, 1)
        self.assertEqual(len(plan.content_hash), 64)

    def test_small_or_suspiciously_shrinking_snapshot_is_rejected(self) -> None:
        small = build_universe_sync_plan(
            universe_id="BIST_ALL",
            source="test:XUTUM",
            as_of=date(2026, 9, 7),
            members=(UniverseMember("ASELS", "ASELS", "Aselsan"),),
            current_symbols=(),
        )
        with self.assertRaisesRegex(ValueError, "alt sınır"):
            validate_universe_sync_plan(small)

        members = tuple(
            UniverseMember(f"A{index:03d}", f"A{index:03d}", f"Company {index}")
            for index in range(300)
        )
        shrinking = build_universe_sync_plan(
            universe_id="BIST_ALL",
            source="test:XUTUM",
            as_of=date(2026, 9, 7),
            members=members,
            current_symbols=tuple(member.symbol for member in members)
            + tuple(f"Z{index:03d}" for index in range(100)),
        )
        with self.assertRaisesRegex(ValueError, "güvenlik freni"):
            validate_universe_sync_plan(shrinking)
        validate_universe_sync_plan(shrinking, allow_large_removal=True)


if __name__ == "__main__":
    unittest.main()
