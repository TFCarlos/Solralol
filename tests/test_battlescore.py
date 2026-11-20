from __future__ import annotations

import pytest

from backend.battlescore import VERSION as CURRENT_VERSION
from backend.battlescore_v2_3 import (
    COEFFICIENTS, DECAY_START_MS, MINIMUM_SCORE, ROLE_MULTIPLIERS, VERSION,
    apply_decay, apply_reward, apply_reward_with_adjustments, calculate_match,
)
from backend.soloq_analyses import _attach_battlescore
from backend.battlescore_v2_0 import VERSION as PREVIOUS_V2_0_VERSION
from backend.battlescore_v2_1 import VERSION as PREVIOUS_VERSION


def _players(count=1, **common):
    return [{"participantId": pid, "teamId": 100 if pid <= count // 2 + (count % 2) else 200,
             **common} for pid in range(1, count + 1)]


def _row(result, pid=1):
    return next(row for row in result["participants"] if row["participantId"] == pid)


def _series_score(row, timestamp):
    return next(point["score"] for point in row["series"] if point["timestamp"] == timestamp)


def test_configuration_matches_experimental_coefficients_and_role_table():
    assert VERSION == "battlescore_v2_3"
    assert PREVIOUS_VERSION == "battlescore_v2_1"
    assert PREVIOUS_V2_0_VERSION == "battlescore_v2_0"
    assert COEFFICIENTS == {
        "gold_per_1000": .126, "kill": .156, "assist": .1633, "death": .230,
        "experience_per_1000": .0126, "champion_damage_per_1000": .03255,
        "useful_damage_per_1000": .0186, "epic_monster_damage_per_1000": .00925,
        "epic_monster_damage_cap": .35, "structure_damage_per_1000": .00814,
        "structure_damage_cap": .35, "ward_placed": .0224, "ward_destroyed": .056,
        "vision_event_cap": .45, "final_vision_per_point": .01344, "final_vision_cap": .45,
        "major_objective_secure": .0407, "major_objective_participation": .0222,
        "tower_destroyed": .0296, "structure_participation": .01295,
        "turret_plate": .00814, "turret_plate_cap": .13,
        "allied_heal_shield_per_1000": .0264, "allied_heal_shield_cap": .25,
        "first_blood": .096, "shutdown": .084, "teamfight_participation": .042,
        "teamfight_cap": .18, "objective_steal": .0148, "objective_steal_cap": .12,
        "teamfight_window_ms": 15_000, "teamfight_min_kills": 2,
        "teamfight_min_participants": 4,
    }
    assert ROLE_MULTIPLIERS["JUNGLE"]["gold"] == .70
    assert ROLE_MULTIPLIERS["MIDDLE"]["kills"] == 1.25
    assert ROLE_MULTIPLIERS["BOTTOM"]["champion_damage"] == 1.20
    assert ROLE_MULTIPLIERS["UTILITY"]["allied_utility"] == 1.45


def test_decay_starts_after_two_minutes_and_crosses_two_piecewise():
    assert DECAY_START_MS == 120_000
    assert apply_decay(5, 1) == pytest.approx(4.84)
    assert apply_decay(2.1, 1) == pytest.approx(1.9625)
    assert apply_decay(.2, 10) == MINIMUM_SCORE
    row = _row(calculate_match("decay", _players(), [], [{"timestamp": 0, "participantId": 1, "gold": 0}], 180))
    assert row["finalScore"] == pytest.approx(4.84)
    assert _series_score(row, 120_000) == pytest.approx(5)


def test_recovery_bands_split_at_three_four_and_ten():
    assert apply_reward(2.5, .2) == pytest.approx(2.72)
    assert apply_reward(3.5, .2) == pytest.approx(3.71)
    assert apply_reward(4.0, .2) == pytest.approx(4.2)
    score, recovery, diminishing = apply_reward_with_adjustments(9.9, .4)
    assert score == pytest.approx(10.0)
    assert recovery == pytest.approx(0)
    assert diminishing == pytest.approx(-.30)


def test_gold_and_experience_are_incremental_with_first_frame_baseline():
    frames = [
        {"timestamp": 0, "participantId": 1, "gold": 500, "xp": 100},
        {"timestamp": 60_000, "participantId": 1, "gold": 1_500, "xp": 1_100},
        {"timestamp": 120_000, "participantId": 1, "gold": 900, "xp": 900},
        {"timestamp": 180_000, "participantId": 1, "gold": 1_900, "xp": 1_900},
    ]
    row = _row(calculate_match("income", [{"participantId": 1, "role": "MIDDLE"}], [], frames, 180))
    assert row["breakdown"]["gold"] == pytest.approx(.1764)
    assert row["breakdown"]["experience"] == pytest.approx(.024948)
    assert row["componentAvailability"]["gold"] == "partial"


def test_role_phase_context_is_bounded_and_preserves_base_economic_reward():
    players = [
        {"participantId": 1, "teamId": 100, "role": "JUNGLE"},
        {"participantId": 6, "teamId": 200, "role": "JUNGLE"},
    ]
    frames = []
    for timestamp, g1, g6 in ((0, 500, 500), (60_000, 1_500, 1_500), (120_000, 2_500, 3_000)):
        frames.extend([{"timestamp": timestamp, "participantId": 1, "gold": g1},
                       {"timestamp": timestamp, "participantId": 6, "gold": g6}])
    baseline = {"version": "fixture", "metrics": {"JUNGLE": {"early": {"gold": {"available": True, "matches": 30, "medianPerMinute": 1000}}}}}
    row = _row(calculate_match("normalized", players, [], frames, 120, baseline))
    assert row["breakdown"]["gold"] == pytest.approx(.1764 - .00275625)
    assert row["breakdown"]["contextual_adjustment"] == pytest.approx(-.00275625)
    assert "same_role_opponent" in row["context"]["used"]
    assert row["context"]["confidence"] == "local_reference"


def test_normal_role_phase_performance_keeps_full_linear_reward():
    players = [{"participantId": 1, "role": "JUNGLE"}]
    baseline = {"metrics": {"JUNGLE": {"early": {"gold": {"available": True, "matches": 25, "medianPerMinute": 1000}}}}}
    frames = [{"timestamp": 0, "participantId": 1, "gold": 500},
              {"timestamp": 60_000, "participantId": 1, "gold": 1500}]
    row = _row(calculate_match("expected-level", players, [], frames, 60, baseline))
    assert row["breakdown"]["gold"] == pytest.approx(.126 * .70)
    assert row["breakdown"]["contextual_adjustment"] == pytest.approx(0)


def test_insufficient_reference_data_uses_linear_reward_even_with_enemy_observation():
    players = [{"participantId": 1, "teamId": 100, "role": "JUNGLE"},
               {"participantId": 6, "teamId": 200, "role": "JUNGLE"}]
    frames = [{"timestamp": t, "participantId": pid, "gold": amount}
              for t, ours, enemy in ((0, 0, 0), (60_000, 1000, 2000))
              for pid, amount in ((1, ours), (6, enemy))]
    row = _row(calculate_match("no-baseline", players, [], frames, 60))
    assert row["breakdown"]["gold"] == pytest.approx(.126 * .70)
    assert row["breakdown"]["contextual_adjustment"] == pytest.approx(0)


def test_champion_damage_timeline_and_final_fallback_are_champion_only():
    frames = [
        {"timestamp": 0, "participantId": 1, "championDamageDealt": 0, "allSourceDamageReceived": 999_000},
        {"timestamp": 60_000, "participantId": 1, "championDamageDealt": 10_000, "allSourceDamageReceived": 1_500_000},
    ]
    row = _row(calculate_match("damage", [{"participantId": 1, "role": "BOTTOM"}], [], frames, 60))
    assert row["breakdown"]["champion_damage"] == pytest.approx(.3906)
    assert row["breakdown"].get("all_source_damage_received", 0) == 0
    final_only = _row(calculate_match("damage-final", [{"participantId": 1, "role": "BOTTOM", "championDamageDealt": 10_000}], [],
        [{"timestamp": 0, "participantId": 1, "gold": 500}], 600))
    assert final_only["breakdown"]["champion_damage"] == pytest.approx(.3906)
    assert "champion_damage_final_only" in final_only["distributed"]
    assert final_only["series"][-1]["timestamp"] == 600_000


def test_useful_damage_is_champion_sourced_incremental_kp_weighted_and_role_adjusted():
    events = [
        {"id": "d1", "timestamp": 20_000, "type": "CHAMPION_KILL", "killerId": 2, "victimId": 1,
         "championDamageReceivedObserved": True, "championDamageReceivedDelta": 2_000, "killParticipationAtEvent": .5},
        {"id": "d2", "timestamp": 40_000, "type": "CHAMPION_KILL", "killerId": 3, "victimId": 1,
         "championDamageReceivedObserved": True, "championDamageReceivedDelta": 2_000, "killParticipationAtEvent": .5},
        {"id": "d3", "timestamp": 50_000, "type": "CHAMPION_KILL", "killerId": 2, "victimId": 1,
         "championDamageReceivedDelta": 99_000, "allSourceDamageReceivedDelta": 99_000},
    ]
    row = _row(calculate_match("useful", [{"participantId": 1, "role": "TOP"}, {"participantId": 2}, {"participantId": 3}], events, [], 60))
    assert row["usefulDamageReceived"] == pytest.approx(2_000)
    assert row["breakdown"]["useful_damage"] == pytest.approx(.0186 * 2 * 1.35)
    assert row["breakdown"]["death_penalties"] == pytest.approx(-3 * .23 * 1.05)


def test_deaths_are_role_weighted_and_not_recovery_boosted():
    events = [{"id": f"d{i}", "timestamp": 10_000 + i * 5_000, "type": "CHAMPION_KILL", "killerId": 2,
               "victimId": 1, "assistingIds": []} for i in range(2)]
    row = _row(calculate_match("death", [{"participantId": 1, "role": "BOTTOM"}, {"participantId": 2}], events, [], 120))
    assert row["breakdown"]["death_penalties"] == pytest.approx(-2 * .23 * 1.20)


def test_duplicate_events_without_riot_ids_are_deduplicated_by_verified_fields():
    kill = {"timestamp": 30_000, "type": "CHAMPION_KILL", "killerId": 1, "victimId": 2,
            "assistingIds": [3]}
    result = calculate_match("duplicate-no-id", [{"participantId": 1}, {"participantId": 2}, {"participantId": 3}],
                             [kill, dict(kill)], [], 60)
    assert _row(result, 1)["breakdown"]["kills"] == pytest.approx(.156)
    assert _row(result, 2)["breakdown"]["death_penalties"] == pytest.approx(-.23)
    assert _row(result, 3)["breakdown"]["assists"] == pytest.approx(.1633)


def test_objective_and_structure_caps_are_separate_final_only_rewards():
    player = {"participantId": 1, "role": "TOP", "damageToEpicMonsters": 100_000,
              "damageToBuildings": 100_000, "damageToObjectives": 500_000}
    row = _row(calculate_match("objectives", [player], [], [{"timestamp": 0, "participantId": 1, "gold": 0}], 600))
    assert row["breakdown"]["objective_damage"] == pytest.approx(.35)
    assert row["breakdown"]["structure_damage"] == pytest.approx(.35 * 1.50)
    assert row["distributed"] == ["epic_damage_final_only", "structure_damage_final_only"]
    assert row["series"][-1]["timestamp"] == 600_000
    aggregate = _row(calculate_match("aggregate-only", [{"participantId": 1, "damageToObjectives": 50_000}], [],
                                    [{"timestamp": 0, "participantId": 1, "gold": 0}], 60))
    assert aggregate["breakdown"]["objective_damage"] == 0


def test_vision_final_fallback_is_capped_and_not_double_counted_with_partial_events():
    events = [{"id": "w1", "timestamp": 10_000, "type": "WARD_PLACED", "participantId": 1}]
    row = _row(calculate_match("vision", [{"participantId": 1, "role": "UTILITY", "vision": 100,
        "wardsPlaced": 30, "wardsKilled": 10}], events, [], 120))
    assert row["breakdown"]["vision"] == pytest.approx(.45 * 1.25)
    assert row["distributed"] == ["vision_final_only"]
    complete = _row(calculate_match("vision-complete", [{"participantId": 1, "role": "UTILITY", "vision": 40,
        "wardsPlaced": 1, "wardsKilled": 1}], [
        {"id": "wp", "timestamp": 10_000, "type": "WARD_PLACED", "participantId": 1},
        {"id": "wk", "timestamp": 20_000, "type": "WARD_KILL", "killerId": 1}], [], 60))
    assert complete["breakdown"]["vision"] == pytest.approx((.0224 + .056) * 1.25)


def test_verified_healing_shielding_uses_teammate_fields_and_caps():
    row = _row(calculate_match("utility", [{"participantId": 1, "role": "UTILITY",
        "totalHealsOnTeammates": 20_000, "totalDamageShieldedOnTeammates": 20_000}], [],
        [{"timestamp": 0, "participantId": 1, "gold": 0}], 60))
    assert row["breakdown"]["allied_heal_shield"] == pytest.approx(.25 * 1.45)
    missing = _row(calculate_match("utility-missing", [{"participantId": 1, "totalHeal": 99_000}], [],
        [{"timestamp": 0, "participantId": 1, "gold": 0}], 60))
    assert missing["breakdown"]["allied_heal_shield"] == 0
    assert missing["componentAvailability"]["allied_heal_shield"] == "unavailable"


def test_confirmed_bonus_attributions_and_objective_participation():
    participants = [{"participantId": pid, "teamId": 100 if pid <= 5 else 200} for pid in range(1, 11)]
    events = [
        {"id": "first", "timestamp": 20_000, "type": "CHAMPION_KILL", "killerId": 1, "victimId": 6,
         "assistingIds": [2], "shutdownBounty": 700},
        {"id": "dragon", "timestamp": 30_000, "type": "ELITE_MONSTER_KILL", "killerId": 1, "monsterType": "DRAGON", "assistingIds": [2]},
        {"id": "tower", "timestamp": 40_000, "type": "BUILDING_KILL", "killerId": 1, "buildingType": "TOWER_BUILDING", "assistingIds": [2]},
    ]
    result = calculate_match("verified", participants, events, [], 120)
    assert _row(result, 1)["breakdown"]["first_blood"] == pytest.approx(.096)
    assert _row(result, 1)["breakdown"]["shutdown"] == pytest.approx(.084)
    assert _row(result, 2)["breakdown"]["objective_participation"] == pytest.approx(.0222)
    assert _row(result, 2)["breakdown"]["structure_participation"] == pytest.approx(.01295)


def test_teamfight_and_plate_bonuses_are_verified_and_capped():
    participants = [{"participantId": pid, "teamId": 100 if pid <= 5 else 200} for pid in range(1, 11)]
    events = []
    for group in range(12):
        start = group * 30_000
        for suffix, stamp, killer, victim in (("a", start + 1_000, 1, 6), ("b", start + 5_000, 2, 7)):
            events.append({"id": f"{group}-{suffix}", "timestamp": stamp, "type": "CHAMPION_KILL",
                           "killerId": killer, "victimId": victim, "assistingIds": [3, 8]})
        if group < 8:
            events.append({"id": f"plate-{group}", "timestamp": start + 10_000, "type": "TURRET_PLATE_DESTROYED", "killerId": 1})
    row = _row(calculate_match("caps", participants, events, [], 600))
    assert row["breakdown"]["teamfight_participation"] == pytest.approx(.18)
    assert row["breakdown"]["turret_plate"] == pytest.approx(8 * .00814)


def test_ten_participants_final_scores_match_chart_and_breakdown_reconciles():
    players = [{"participantId": pid, "teamId": 100 if pid <= 5 else 200,
                "role": ["TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"][(pid - 1) % 5]} for pid in range(1, 11)]
    frames = [{"timestamp": ts, "participantId": pid, "gold": 500 + ts / 60_000 * 1200,
               "xp": ts / 60_000 * 500, "championDamageDealt": ts / 60_000 * 600}
              for pid in range(1, 11) for ts in (0, 60_000, 120_000)]
    result = calculate_match("ten", players, [], frames, 120)
    assert len(result["participants"]) == 10
    for row in result["participants"]:
        assert row["series"][-1]["score"] == row["finalScore"]
        b = row["breakdown"]
        reconciled = sum(value for key, value in b.items() if key not in {"final_score", "contextual_adjustment"})
        assert reconciled == pytest.approx(row["finalScore"])
        assert row["audit"]["reconciles"] is True
        assert row["audit"]["reconciledScore"] == pytest.approx(row["finalScore"])
        assert MINIMUM_SCORE <= row["finalScore"] <= 10.0


def test_repeated_calculation_is_deterministic_and_old_scores_invalidate():
    record = {"battle_score": {"version": "battlescore_v2_7"}}
    players = [{"participantId": 1, "role": "MIDDLE"}]
    frames = [{"timestamp": 0, "participantId": 1, "gold": 500}, {"timestamp": 60_000, "participantId": 1, "gold": 1_500}]
    first = _attach_battlescore(record, players, "id", [], frames, 60)
    second = _attach_battlescore(record, players, "id", [], frames, 60)
    assert first["version"] == CURRENT_VERSION
    assert first["inputFingerprint"] == second["inputFingerprint"]
    assert first["participants"][0]["finalScore"] == second["participants"][0]["finalScore"]
