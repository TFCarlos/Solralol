from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import battlescore_v2_3
from backend import battlescore_v2_5 as current


FIXTURE = Path(__file__).parent.parent / "docs" / "battlescore_v2_2_reference_fixture.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_v2_5_configuration_changes_only_decay_gold_and_death():
    assert current.VERSION == "battlescore_v2_5"
    assert current.DECAY_START_MS == 120_000
    assert current.DECAY_PER_MINUTE == pytest.approx(.14)
    assert current.PROTECTED_DECAY_PER_MINUTE == pytest.approx(.085)
    assert current.COEFFICIENTS["gold_per_1000"] == pytest.approx(.142)
    assert current.COEFFICIENTS["death"] == pytest.approx(.270)
    assert current.ROLE_MULTIPLIERS == battlescore_v2_3.ROLE_MULTIPLIERS
    for key in current.COEFFICIENTS.keys() - {"gold_per_1000", "death"}:
        assert current.COEFFICIENTS[key] == battlescore_v2_3.COEFFICIENTS[key]


def test_first_two_minutes_have_no_decay_then_elapsed_time_is_charged():
    result = current.calculate_match("decay", [
        {"participantId": 1, "role": "MIDDLE"},
    ], [], [
        {"timestamp": 0, "participantId": 1, "gold": 500, "xp": 0},
        {"timestamp": 120_000, "participantId": 1, "gold": 500, "xp": 0},
        {"timestamp": 180_000, "participantId": 1, "gold": 500, "xp": 0},
    ], 180)
    row = result["participants"][0]
    score_at = lambda timestamp: next(point["score"] for point in reversed(row["series"])
                                      if point["timestamp"] <= timestamp)
    assert score_at(120_000) == pytest.approx(5.0)
    assert score_at(180_000) == pytest.approx(4.86)
    assert row["breakdown"]["time_decay"] == pytest.approx(-.14)


def test_decay_crossing_two_uses_both_rates_piecewise():
    after = current.apply_decay(2.1, 1.0)
    assert after == pytest.approx(2.0 - .085 * (1.0 - (.1 / .14)))
    assert current.apply_decay(2.0, 1.0) == pytest.approx(1.915)


def test_gold_rewards_only_positive_cumulative_increments_and_keeps_role_rate():
    result = current.calculate_match("gold", [
        {"participantId": 1, "role": "MIDDLE"},
    ], [], [
        {"timestamp": 0, "participantId": 1, "gold": 500, "xp": 0},
        {"timestamp": 60_000, "participantId": 1, "gold": 1_500, "xp": 0},
        {"timestamp": 90_000, "participantId": 1, "gold": 1_300, "xp": 0},
        {"timestamp": 120_000, "participantId": 1, "gold": 1_700, "xp": 0},
    ], 120)
    row = result["participants"][0]
    assert row["breakdown"]["gold"] == pytest.approx(1.2 * .142)
    assert row["audit"]["roleAdjustedBaseByMetric"]["gold"] == pytest.approx(1.2 * .142)


def test_death_is_immediate_deduplicated_and_keeps_jungle_role_multiplier():
    death = {"id": "verified-death", "timestamp": 45_000, "type": "CHAMPION_KILL",
             "killerId": 2, "victimId": 1, "assistingIds": []}
    result = current.calculate_match("death", [
        {"participantId": 1, "role": "JUNGLE"},
        {"participantId": 2, "role": "MIDDLE"},
    ], [death, dict(death)], [], 90)
    row = next(item for item in result["participants"] if item["participantId"] == 1)
    assert row["deaths"] == 1
    assert row["breakdown"]["death_penalties"] == pytest.approx(-.270 * 1.15)
    before, after = [point["score"] for point in row["series"] if point["timestamp"] == 45_000]
    assert after - before == pytest.approx(-.270 * 1.15)


def test_reference_match_recalculation_improves_early_curve_and_reconciles_all_players():
    fixture = _fixture()
    args = ("reference-match", fixture["participants"], fixture["events"], fixture["frames"],
            fixture["match_duration_seconds"], fixture["calibration_baselines"])
    before = battlescore_v2_3.calculate_match(*args)
    after = current.calculate_match(*args)
    previous = {row["participantId"]: row for row in before["participants"]}
    recalculated = {row["participantId"]: row for row in after["participants"]}
    briar = recalculated[7]
    old_briar = previous[7]

    score_at = lambda row, minute: next(point["score"] for point in reversed(row["series"])
                                        if point["timestamp"] <= minute * 60_000)
    assert current.VERSION == after["version"]
    assert score_at(briar, 8) > score_at(old_briar, 8)
    assert briar["finalScore"] == pytest.approx(5.721152708744185, abs=1e-9)
    assert briar["series"][-1]["score"] == briar["finalScore"]
    targets = {int(key): value for key, value in fixture["targets"].items()}
    mae = sum(abs(row["finalScore"] - targets[row["participantId"]]) for row in after["participants"]) / 10
    assert mae == pytest.approx(.4866761925331019, abs=1e-9)
    assert mae <= .5
    for row in after["participants"]:
        assert row["audit"]["reconciles"]
        assert row["series"][-1]["score"] == row["finalScore"]
        assert .1 <= row["finalScore"] <= 10

