from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import battlescore_engine as current
from backend import battlescore_v2_5 as previous


FIXTURE = Path(__file__).parent.parent / "docs" / "battlescore_v2_2_reference_fixture.json"


def test_current_v2_7_keeps_gold_experience_and_other_rules_from_v2_6():
    assert current.VERSION == "battlescore_v2_7"
    assert current.COEFFICIENTS["gold_per_1000"] == pytest.approx(.150)
    assert current.COEFFICIENTS["experience_per_1000"] == pytest.approx(.014)
    assert current.DECAY_PER_MINUTE == previous.DECAY_PER_MINUTE
    assert current.PROTECTED_DECAY_PER_MINUTE == previous.PROTECTED_DECAY_PER_MINUTE
    assert current.COEFFICIENTS["death"] == previous.COEFFICIENTS["death"]
    assert current.ROLE_MULTIPLIERS["TOP"]["kills"] == pytest.approx(1.05)
    assert current.ROLE_MULTIPLIERS["TOP"]["experience"] == pytest.approx(1.05)
    assert current.ROLE_MULTIPLIERS["JUNGLE"]["gold"] == pytest.approx(.85)
    assert current.ROLE_MULTIPLIERS["JUNGLE"]["structure_damage"] == pytest.approx(.85)
    assert current.ROLE_MULTIPLIERS["MIDDLE"]["kills"] == pytest.approx(1.15)
    assert current.ROLE_MULTIPLIERS["UTILITY"]["gold"] == pytest.approx(.70)
    assert current.ROLE_MULTIPLIERS["UTILITY"]["assists"] == pytest.approx(1.20)
    for key in current.COEFFICIENTS.keys() - {"gold_per_1000", "experience_per_1000"}:
        assert current.COEFFICIENTS[key] == previous.COEFFICIENTS[key]


def test_final_only_rewards_are_identified_estimates_without_an_end_spike():
    result = current.calculate_match("final-only", [{
        "participantId": 1, "role": "MIDDLE", "championDamageDealt": 10_000,
        "damageToEpicMonsters": 5_000, "damageToBuildings": 5_000, "vision": 20,
        "totalHealsOnTeammates": 5_000,
    }], [{"id": "unscored-source-record", "timestamp": 0, "type": "OTHER"}], [], 600)
    row = result["participants"][0]
    assert row["distributed"] == [
        "champion_damage_final_only_estimated_linear",
        "epic_damage_final_only_estimated_linear",
        "healing_shielding_final_only_estimated_linear",
        "structure_damage_final_only_estimated_linear",
        "vision_final_only_estimated_linear",
    ]
    assert row["breakdown"]["champion_damage"] == pytest.approx(.35805)
    assert row["breakdown"]["objective_damage"] == pytest.approx(.04625)
    assert row["breakdown"]["structure_damage"] == pytest.approx(.0407)
    assert row["breakdown"]["vision"] == pytest.approx(.25536)
    assert row["breakdown"]["allied_heal_shield"] == pytest.approx(.1188)
    end_timestamp = result["matchDurationMs"]
    before_end = [point for point in row["series"] if point["timestamp"] < end_timestamp][-1]
    end_points = [point for point in row["series"] if point["timestamp"] == end_timestamp]
    assert end_points[-1]["score"] == row["finalScore"]
    assert end_points[-1]["score"] - before_end["score"] < .02

    assert row["audit"]["reconciles"]


def test_reference_match_final_point_remains_the_calculated_score_and_tail_is_quiet():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = current.calculate_match("reference", fixture["participants"], fixture["events"],
        fixture["frames"], fixture["match_duration_seconds"], fixture["calibration_baselines"])
    briar = next(row for row in result["participants"] if row["champion"] == "Briar")
    assert result["version"] == current.VERSION
    assert briar["series"][-1]["score"] == briar["finalScore"]
    end = result["matchDurationMs"]
    final_points = [point for point in briar["series"] if point["timestamp"] == end]
    assert final_points[-1]["score"] - final_points[-2]["score"] < .02
    assert "vision_final_only_estimated_linear" in briar["distributed"]
