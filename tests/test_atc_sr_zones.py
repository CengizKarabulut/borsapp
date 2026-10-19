from __future__ import annotations

import json
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts.atc_sr_zones import build_sr_zones

START = datetime(2020, 1, 1, tzinfo=UTC)


def frame_for(prices):
    bars = tuple(SimpleNamespace(open_time=START + timedelta(days=index),
                                 close_time=START + timedelta(days=index + 1),
                                 open=float(opened), high=float(high), low=float(low), close=float(close))
                 for index, (opened, high, low, close) in enumerate(prices))
    return SimpleNamespace(symbol_at_snapshot="FIXTURE", source="test", timeframe="1d",
                           price_basis="split_adjusted", snapshot_id="synthetic", series_revision=1,
                           quality="complete", is_partial=False, bars=bars)


def pivot_prices():
    prices = [(105, 106, 104, 105)] * 30
    prices[26] = (105, 106, 100, 105)
    return prices


def two_bounces():
    return pivot_prices() + [
        (100.3, 100.6, 100.1, 100.4), (100.4, 104, 100.2, 104),
        (104, 105, 103, 104),
        (100.3, 100.6, 100.1, 100.4), (100.4, 105, 100.2, 104),
    ]


def run(frame, **options):
    return build_sr_zones(frame, as_of=START + timedelta(days=1000), **options)


def support(result):
    return next(row for row in result["zones"] if row["side"] == "support" and row["center"] == 100)


class CausalPivotZoneTests(unittest.TestCase):
    def test_pivot_uses_three_right_closes_and_does_not_count_its_own_reversal(self):
        prices = pivot_prices()
        prices[27] = (105, 106, 99, 105)
        prices.append((105, 106, 104, 105))
        frame = frame_for(prices)
        early = build_sr_zones(frame, as_of=frame.bars[29].close_time)
        self.assertFalse(any(row["center"] == 99 for row in early["zones"]))
        ready = run(frame)
        zone = next(row for row in ready["zones"] if row["center"] == 99)
        self.assertEqual(zone["confirmed_at"], frame.bars[30].close_time.isoformat())
        self.assertEqual(zone["completed_visits"], 0)
        self.assertEqual(ready["supports"], [])

    def test_future_and_open_prices_cannot_rewrite_prefix(self):
        frame = frame_for(two_bounces() + [(104, 105, 103, 104)] * 4)
        cutoff = frame.bars[34].close_time
        prefix = deepcopy(frame)
        prefix.bars = prefix.bars[:35]
        actual = build_sr_zones(frame, as_of=cutoff)
        expected = build_sr_zones(prefix, as_of=cutoff)
        for key in ("zones", "supports", "resistances", "episodes", "reference_price"):
            self.assertEqual(actual[key], expected[key])
        open_frame = deepcopy(frame)
        open_frame.bars = open_frame.bars[:36]
        open_frame.is_partial, open_frame.quality = True, "preliminary"
        open_frame.bars[-1].open = 1
        open_frame.bars[-1].high, open_frame.bars[-1].low = 10000, 0.01
        open_frame.bars[-1].close = 9000
        open_result = run(open_frame)
        self.assertEqual(open_result["zones"], expected["zones"])
        self.assertEqual(open_result["episodes"], expected["episodes"])

    def test_zone_geometry_frozen_while_later_nearby_pivot_joins(self):
        initial = run(frame_for(pivot_prices()))
        later = run(frame_for(two_bounces() + [(104, 105, 103, 104)] * 4))
        first, final = support(initial), support(later)
        for field in ("zone_id", "center", "lower", "upper", "creation_atr", "confirmed_at"):
            self.assertEqual(first[field], final[field])
        self.assertGreater(final["member_count"], 1)
        self.assertEqual(first["member_count"], 1)

    def test_two_distinct_completed_bounces_enable_memory_not_probability(self):
        result = run(frame_for(two_bounces()))
        zone = support(result)
        episodes = [row for row in result["episodes"] if row["zone_id"] == zone["zone_id"]]
        self.assertEqual([row["status"] for row in episodes], ["bounce", "bounce"])
        self.assertEqual(zone["completed_visits"], 2)
        self.assertTrue(zone["memory_ready"])
        self.assertFalse(zone["score_is_probability"])
        self.assertGreater(zone["memory_score"], 0.5)
        self.assertEqual(result["supports"][0]["zone_id"], zone["zone_id"])
        self.assertTrue(result["research_only"])
        self.assertFalse(result["production_validated"])
        self.assertFalse(result["algorithm"]["changes_stop_tp"])

    def test_episode_entry_atr_precedes_its_extreme_range(self):
        prefix = run(frame_for(pivot_prices()))
        zone = support(prefix)
        prices = pivot_prices() + [(100.3, 101, 80, 100.4)]
        result = run(frame_for(prices))
        episode = next(row for row in result["episodes"] if row["zone_id"] == zone["zone_id"])
        self.assertAlmostEqual(episode["entry_atr"], zone["creation_atr"])
        self.assertEqual(episode["status"], "penetration")

    def test_same_ohlc_bar_hits_both_barriers_is_ambiguous(self):
        result = run(frame_for(pivot_prices() + [(100.3, 110, 90, 100.4)]))
        zone = support(result)
        episode = next(row for row in result["episodes"] if row["zone_id"] == zone["zone_id"])
        self.assertEqual(episode["status"], "ambiguous_both_barriers")
        self.assertEqual(zone["completed_visits"], 0)
        self.assertEqual(zone["memory_score"], 0.5)

    def test_favorable_high_on_intrabar_entry_is_not_assumed_after_touch(self):
        result = run(frame_for(pivot_prices() + [(105, 106, 100.1, 100.4)]))
        zone = support(result)
        episode = next(row for row in result["episodes"] if row["zone_id"] == zone["zone_id"])
        self.assertEqual(episode["status"], "ambiguous_entry_bar")
        self.assertEqual(zone["completed_visits"], 0)

    def test_gap_skipping_zone_is_never_a_successful_filled_touch(self):
        result = run(frame_for(pivot_prices() + [(98, 100.4, 97, 99)]))
        zone = support(result)
        episode = next(row for row in result["episodes"] if row["zone_id"] == zone["zone_id"])
        self.assertEqual(episode["status"], "ambiguous_gap_entry")
        self.assertEqual(zone["completed_visits"], 0)

    def test_ten_staying_bars_are_one_timeout_not_ten_touches(self):
        prices = pivot_prices() + [(100.3, 100.5, 100.1, 100.3)] * 10
        result = run(frame_for(prices))
        zone = support(result)
        episodes = [row for row in result["episodes"] if row["zone_id"] == zone["zone_id"]]
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["status"], "timeout")
        self.assertEqual(episodes[0]["resolved_index"] - episodes[0]["entry_index"] + 1, 10)
        self.assertEqual(zone["completed_visits"], 0)

    def test_pending_result_does_not_use_future_outcome(self):
        frame = frame_for(two_bounces())
        pending = build_sr_zones(frame, as_of=frame.bars[30].close_time)
        zone = support(pending)
        self.assertEqual(zone["pending_episode"]["status"], "pending")
        self.assertEqual(zone["completed_visits"], 0)
        self.assertEqual(pending["episodes"], [])
        complete = run(frame)
        self.assertEqual(support(complete)["completed_visits"], 2)

    def test_memory_decays_toward_neutral_without_becoming_probability(self):
        first = support(run(frame_for(two_bounces())))
        later = support(run(frame_for(two_bounces() + [(104, 105, 103, 104)] * 60)))
        self.assertAlmostEqual(later["bounce_weight"], first["bounce_weight"] / 2)
        self.assertGreater(later["memory_score"], 0.5)
        self.assertLess(later["memory_score"], first["memory_score"])

    def test_broken_visit_stays_in_memory_and_requires_return_before_another(self):
        prices = pivot_prices() + [(100.3, 100.6, 100.1, 100.4), (100.4, 100.5, 97, 98)]
        prices += [(98, 99, 97, 98)] * 4
        prices += [(98, 105, 98, 104), (100.3, 100.6, 100.1, 100.4), (100.4, 105, 100.2, 104)]
        result = run(frame_for(prices))
        zone = support(result)
        episodes = [row for row in result["episodes"] if row["zone_id"] == zone["zone_id"]]
        self.assertEqual([row["status"] for row in episodes], ["penetration", "bounce"])
        self.assertEqual(zone["completed_visits"], 2)
        self.assertGreater(zone["penetration_weight"], 0)

    def test_support_and_resistance_episode_logic_are_mirrored(self):
        prices = two_bounces()
        mirrored = [(200 - opened, 200 - low, 200 - high, 200 - close)
                    for opened, high, low, close in prices]
        result = run(frame_for(mirrored))
        zone = next(row for row in result["zones"] if row["side"] == "resistance" and row["center"] == 100)
        episodes = [row for row in result["episodes"] if row["zone_id"] == zone["zone_id"]]
        self.assertEqual([row["status"] for row in episodes], ["bounce", "bounce"])
        self.assertEqual(result["resistances"][0]["zone_id"], zone["zone_id"])

    def test_one_move_cannot_be_multiple_independent_same_side_visits(self):
        prices = pivot_prices() + [(108, 110, 107, 108)] * 6
        prices[32] = (108, 110, 95, 108)
        prices += [(108, 110, 94, 106)]
        result = run(frame_for(prices))
        self.assertGreaterEqual(len([zone for zone in result["zones"] if zone["side"] == "support"]), 2)
        entries = [row for row in result["episodes"] if row["side"] == "support" and row["entry_index"] == 36]
        self.assertEqual(len(entries), 1)
        self.assertIn("support", entries[0]["zone_id"])

    def test_rightmost_equal_pivot_is_selected(self):
        prices = pivot_prices()
        prices[27] = prices[26]
        prices += [(105, 106, 104, 105)]
        frame = frame_for(prices)
        zone = support(run(frame))
        self.assertEqual(zone["pivot_at"], frame.bars[27].close_time.isoformat())
        self.assertEqual(zone["confirmed_at"], frame.bars[30].close_time.isoformat())

    def test_zone_expires_by_seed_pivot_not_latest_member(self):
        result = run(frame_for(two_bounces() + [(104, 105, 103, 104)] * 115))
        zone = support(result)
        self.assertTrue(zone["retired"])
        self.assertGreaterEqual(zone["age_bars"], 120)
        self.assertNotIn(zone["zone_id"], [row["zone_id"] for row in result["supports"]])

    def test_suspicious_price_basis_jump_rejected_by_default(self):
        result = run(frame_for(two_bounces() + [(50, 51, 49, 50)]))
        self.assertEqual(result["status"], "unavailable_suspected_discontinuity")
        self.assertEqual(result["supports"], [])
        self.assertEqual(result["zones"], [])
        self.assertFalse(result["discontinuities"][0]["verified_corporate_action"])

    def test_explicit_reset_policy_forgets_old_zones_and_atr_requires_new_warmup(self):
        prices = two_bounces() + [(50, 51, 49, 50)] * 29
        result = run(frame_for(prices), discontinuity_policy="reset")
        self.assertEqual(result["status"], "insufficient_history")
        self.assertEqual(result["segment_bars_available"], 29)
        self.assertEqual(result["supports"], [])
        ready = run(frame_for(prices + [(50, 51, 49, 50)]), discontinuity_policy="reset")
        self.assertEqual(ready["status"], "ready_research_only")
        self.assertFalse(any(row["center"] == 100 for row in ready["zones"]))
        self.assertEqual(len(ready["reset_events"]), 1)

    def test_caller_declared_boundary_censors_open_visit_without_a_false_loss(self):
        frame = frame_for(pivot_prices() + [(100.3, 100.6, 100.1, 100.4), (50, 51, 49, 50)])
        result = run(frame, reset_at=[frame.bars[-1].close_time])
        self.assertEqual(result["episodes"][0]["status"], "censored_reset")
        self.assertEqual(result["reset_events"][0]["reason"], "explicit_boundary")
        with self.assertRaisesRegex(ValueError, "reset_timestamp"):
            run(frame, reset_at=[frame.bars[-1].close_time - timedelta(hours=1)])

    def test_volume_is_optional_and_never_fabricated_or_used(self):
        frame = frame_for(two_bounces())
        absent = run(frame)
        for index, bar in enumerate(frame.bars):
            bar.volume = float("nan") if index % 2 else 1e99
        present = run(frame)
        self.assertEqual(absent, present)
        self.assertFalse(present["algorithm"]["volume_used"])

    def test_json_provenance_and_no_mutation(self):
        frame = frame_for(two_bounces())
        original = deepcopy(frame)
        result = run(frame)
        self.assertEqual(frame, original)
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)
        for key in ("source", "timeframe", "price_basis", "snapshot_id", "series_revision"):
            self.assertEqual(result[key], getattr(frame, key))
        self.assertTrue(result["unvalidated_on_corrected_feed"])

    def test_invalid_inputs_fail_clearly_and_bad_quality_never_produces_zones(self):
        frame = frame_for(two_bounces())
        for policy in (None, "adjust", "ignore"):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                run(frame, discontinuity_policy=policy)
        for tick in (0, -1, float("nan"), True):
            with self.subTest(tick=tick), self.assertRaises(ValueError):
                run(frame, tick_size=tick)
        with self.assertRaisesRegex(ValueError, "timezone"):
            build_sr_zones(frame, as_of=datetime(2026, 1, 1))
        broken = deepcopy(frame)
        broken.bars[0].low = -1
        with self.assertRaisesRegex(ValueError, "positive"):
            run(broken)
        broken = deepcopy(frame)
        broken.bars[1].open_time = broken.bars[0].open_time
        with self.assertRaisesRegex(ValueError, "ordered"):
            run(broken)
        frame.quality = "incomplete"
        result = run(frame)
        self.assertEqual(result["status"], "unavailable_data_quality")
        self.assertEqual(result["zones"], [])

    def test_known_tick_size_is_respected_without_inventing_one(self):
        default = support(run(frame_for(pivot_prices())))
        explicit = support(run(frame_for(pivot_prices()), tick_size=2))
        self.assertGreater(default["upper"] - default["center"], 0)
        self.assertEqual(explicit["upper"] - explicit["center"], 2)


if __name__ == "__main__":
    unittest.main()
