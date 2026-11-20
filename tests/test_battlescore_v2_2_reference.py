from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend import battlescore_v2_2
from scripts.calibrate_battlescore_v2_2 import build_report


FIXTURE = Path(__file__).parent.parent / "docs" / "battlescore_v2_2_reference_fixture.json"


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_reference_match_calibration_uses_original_riot_telemetry_and_reconciles():
    fixture = _fixture()
    result = battlescore_v2_2.calculate_match(
        "reference-match", fixture["participants"], fixture["events"], fixture["frames"],
        fixture["match_duration_seconds"], fixture["calibration_baselines"],
    )
    assert battlescore_v2_2.VERSION == "battlescore_v2_2"
    assert len(result["participants"]) == 10
    for row in result["participants"]:
        assert battlescore_v2_2.MINIMUM_SCORE <= row["finalScore"] <= battlescore_v2_2.MAXIMUM_SCORE
        assert row["series"][-1]["score"] == row["finalScore"]
        assert row["audit"]["reconciles"] is True
        assert row["audit"]["reconciledScore"] == pytest.approx(row["finalScore"])


def test_reference_labels_report_error_metrics_without_per_champion_rules():
    report = build_report(_fixture())
    metrics = report["metrics"]
    assert report["version"] == battlescore_v2_2.VERSION
    assert metrics["mae"] <= .5
    assert metrics["rmse"] < .5
    assert metrics["maximum_absolute_error"] > metrics["mae"]
    assert metrics["lower_cap_hits"] == 0
    assert metrics["upper_cap_hits"] == 0
    assert report["calibration_method"]["target_population"].startswith("Una partida etiquetada")
    assert set(report["calibration_method"]["family_multipliers"]) == {
        "kills", "assists", "economy", "damage", "objectives", "vision", "utility",
    }
    assert all(row["audit"]["reconciles"] for row in metrics["participants"])


def test_strict_score_ceiling_and_floor_apply_to_extreme_rewards_and_penalties():
    from backend.battlescore_v2_2 import MAXIMUM_SCORE, MINIMUM_SCORE, apply_penalty, apply_reward

    assert apply_reward(9.9, 100) == MAXIMUM_SCORE
    assert apply_reward(MAXIMUM_SCORE, 1) == MAXIMUM_SCORE
    assert apply_penalty(MINIMUM_SCORE, 10) == MINIMUM_SCORE
