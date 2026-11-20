from __future__ import annotations

from copy import deepcopy

import pytest

from backend import analysis_settings
from backend.negative_achievements import DEFINITIONS, default_settings, evaluate


def _participant(**overrides):
    return {
        "participantId": 1, "local": True, "side": "allied", "role": "UTILITY", "champion": "Leona",
        "kills": 0, "deaths": 0, "assists": 0, "cs": 25, "gold": 6000,
        "wardsPlaced": 0, "wardsKilled": 0, "detectorWardsPlaced": 0,
        "vision": 0, "championDamageDealt": 0, "damageToTurrets": 0,
        "totalTimeSpentDead": 0,
        "achievementAvailability": {"kills": True, "deaths": True, "assists": True, "cs": True,
            "gold": True, "wards_placed": True, "wards_killed": True, "control_wards": True,
            "vision": True, "champion_damage": True, "total_time_spent_dead": True},
        **overrides,
    }


def _find(result, achievement_id):
    return next((item for item in result["items"] if item["achievement_id"] == achievement_id), None)


def test_registry_contains_all_twenty_one_requested_improvement_rules():
    assert len(DEFINITIONS) == 21
    assert len({item["id"] for item in DEFINITIONS}) == 21
    defaults = default_settings()
    assert set(defaults["rules"]) == {item["id"] for item in DEFINITIONS}
    assert all(not defaults["rules"][item["id"]]["enabled"] for item in DEFINITIONS if not item.get("supported", True))


def test_role_eligibility_and_configurable_role_factor():
    player = _participant(role="BOTTOM", wardsPlaced=10)
    result = evaluate([player], [], [], 1800, True, default_settings())
    assert _find(result, "dark_map") is not None
    settings = default_settings()
    settings["rules"]["dark_map"]["roles"] = ["UTILITY"]
    assert _find(evaluate([player], [], [], 1800, True, settings), "dark_map") is None
    settings["rules"]["dark_map"]["roles"] = ["BOTTOM"]
    settings["rules"]["dark_map"]["role_factors"]["BOTTOM"] = 0.1
    assert _find(evaluate([player], [], [], 1800, True, settings), "dark_map") is None


def test_severity_thresholds_and_mild_visibility_are_directional():
    player = _participant(role="TOP", deaths=30)
    settings = default_settings()
    settings["show_mild"] = True
    rule = settings["rules"]["too_many_deaths"]
    rule["thresholds"] = {"mild": 1, "moderate": 2, "severe": 3, "critical": 4}
    result = evaluate([player], [], [], 30 * 60, True, settings)
    assert _find(result, "too_many_deaths")["severity"] == "critical"
    settings["rules"]["dark_map"]["thresholds"] = {"mild": 5, "moderate": 4, "severe": 3, "critical": 2}
    player["wardsPlaced"] = 10.5
    assert _find(evaluate([player], [], [], 30 * 60, True, settings), "dark_map")["severity"] == "moderate"
    settings["show_mild"] = False
    assert all(item["severity"] != "mild" for item in evaluate([player], [], [], 30 * 60, True, settings)["items"])


def test_missing_metrics_are_not_zero_and_short_matches_are_not_judged():
    player = _participant(wardsPlaced=None, achievementAvailability={"wards_placed": False})
    result = evaluate([player], [], [], 300, True, default_settings())
    assert _find(result, "dark_map") is None
    assert _find(result, "rough_start") is None


def test_zero_control_wards_is_measured_but_purchases_are_not_used_as_placements():
    player = _participant(role="JUNGLE", detectorWardsPlaced=0)
    player["visionWardsBoughtInGame"] = 8
    result = evaluate([player], [], [], 30 * 60, True, default_settings())
    finding = _find(result, "no_river_control")
    assert finding is not None and finding["measured_value"] == 0


def test_control_ward_timeline_fallback_counts_only_placed_control_wards():
    player = _participant(detectorWardsPlaced=None, achievementAvailability={"control_wards": False})
    events = [
        {"id": "c1", "type": "WARD_PLACED", "actorId": 1, "wardType": "CONTROL_WARD"},
        {"id": "c1", "type": "WARD_PLACED", "actorId": 1, "wardType": "CONTROL_WARD"},
        {"id": "y1", "type": "WARD_PLACED", "actorId": 1, "wardType": "YELLOW_TRINKET"},
    ]
    finding = _find(evaluate([player], events, [], 30 * 60, True, default_settings()), "no_river_control")
    assert finding["measured_value"] == 1


def test_control_ward_fallback_does_not_count_regular_vision_wards():
    player = _participant(detectorWardsPlaced=None, achievementAvailability={"control_wards": False})
    events = [{"id": "vision", "type": "WARD_PLACED", "actorId": 1, "wardType": "VISION_WARD"}]
    finding = _find(evaluate([player], events, [], 30 * 60, True, default_settings()), "no_river_control")
    assert finding["measured_value"] == 0


def test_zero_team_kills_does_not_create_kill_participation_finding():
    team = [_participant(role="UTILITY")] + [
        {"participantId": index, "side": "allied", "role": role, "kills": 0, "deaths": 0, "assists": 0}
        for index, role in zip(range(2, 6), ("TOP", "JUNGLE", "MIDDLE", "BOTTOM"))
    ]
    assert _find(evaluate(team, [], [], 1800, True, default_settings()), "absent_fights") is None


def test_kill_participation_uses_only_complete_five_player_team_kills():
    team = [_participant(role="UTILITY")] + [
        {"participantId": index, "side": "allied", "role": role, "kills": 2, "deaths": 0, "assists": 0}
        for index, role in zip(range(2, 6), ("TOP", "JUNGLE", "MIDDLE", "BOTTOM"))
    ]
    finding = _find(evaluate(team, [], [], 1800, True, default_settings()), "absent_fights")
    assert finding is not None and finding["measured_value"] == 0
    team.pop()
    assert _find(evaluate(team, [], [], 1800, True, default_settings()), "absent_fights") is None


def test_early_death_evidence_uses_configured_window_and_exact_timestamps():
    player = _participant(deaths=3)
    events = [
        {"id": "early", "type": "CHAMPION_KILL", "victimId": 1, "timestamp": 599_999},
        {"id": "late", "type": "CHAMPION_KILL", "victimId": 1, "timestamp": 600_001},
    ]
    settings = default_settings()
    settings["show_mild"] = True
    finding = _find(evaluate([player], events, [], 1800, True, settings), "rough_start")
    assert finding is not None and finding["measured_value"] == 1
    assert [item["timestamp_ms"] for item in finding["evidence"]] == [599_999]
    settings["early_game_window_minutes"] = 11
    finding = _find(evaluate([player], events, [], 1800, True, settings), "rough_start")
    assert finding["measured_value"] == 2


def test_cs_per_minute_is_duration_normalized_and_support_is_exempt():
    adc = _participant(role="BOTTOM", cs=120)
    settings = default_settings()
    settings["show_mild"] = True
    result = evaluate([adc], [], [], 20 * 60, True, settings)
    assert _find(result, "wasted_farm")["measured_value"] == pytest.approx(6)
    support = _participant(role="UTILITY", cs=25)
    assert _find(evaluate([support], [], [], 20 * 60, True, default_settings()), "wasted_farm") is None


def test_same_role_opponent_deficit_requires_verified_timeline_and_role():
    local = _participant(role="MIDDLE", side="allied")
    rival = {"participantId": 6, "side": "enemy", "role": "MIDDLE"}
    frames = [
        {"participantId": 1, "timestamp": 600_000, "gold": 7_000, "xp": 10_000},
        {"participantId": 6, "timestamp": 600_000, "gold": 9_000, "xp": 12_000},
    ]
    result = evaluate([local, rival], [], frames, 1800, True, default_settings())
    assert _find(result, "lane_behind")["measured_value"] == 2_000
    assert _find(result, "xp_behind")["measured_value"] == 2_000
    assert _find(evaluate([local, rival], [], frames, 1800, False, default_settings()), "lane_behind") is None


def test_objective_opportunity_and_other_unreliable_metrics_are_disabled():
    result = evaluate([_participant(role="JUNGLE")], [], [], 1800, True, default_settings())
    assert _find(result, "forgotten_dragons") is None
    assert _find(result, "unattended_objectives") is None
    assert "forgotten_dragons" not in result["unsupported"]  # Needs verified timeline evidence.
    assert {"unattended_objectives", "low_protection", "low_teamfight_presence", "unspent_gold"}.issubset(result["unsupported"])


def test_suppresses_duplicate_vision_score_when_ward_placement_already_identifies_issue():
    player = _participant(role="UTILITY", wardsPlaced=0, vision=0)
    findings = evaluate([player], [], [], 30 * 60, True, default_settings())["items"]
    ids = {item["achievement_id"] for item in findings}
    assert "dark_map" in ids
    assert "blind" not in ids


def test_findings_do_not_mutate_battlescore_or_original_telemetry():
    player = _participant(role="TOP", deaths=12)
    original = deepcopy(player)
    findings = evaluate([player], [], [], 30 * 60, True, default_settings())
    assert _find(findings, "too_many_deaths") is not None
    assert player == original


def test_negative_settings_persist_and_validate_role_thresholds(tmp_path, monkeypatch):
    config = analysis_settings.default_configuration()
    config.pop("configuration_hash", None)
    path = tmp_path / "analysis_settings.json"
    monkeypatch.setattr(analysis_settings, "config_path", lambda: path)
    saved = analysis_settings.save_configuration(config)
    saved["negative_achievements"]["rules"]["rough_start"]["thresholds"]["critical"] = 5
    saved = analysis_settings.save_configuration(saved)
    reloaded = analysis_settings.load_configuration()
    assert reloaded["negative_achievements"]["rules"]["rough_start"]["thresholds"]["critical"] == 5
    invalid = deepcopy(reloaded)
    invalid.pop("configuration_hash", None)
    invalid["negative_achievements"]["rules"]["wasted_farm"]["thresholds"] = {"mild": 4, "moderate": 5, "severe": 6, "critical": 7}
    with pytest.raises(ValueError, match="Farm desperdiciado"):
        analysis_settings.validate_configuration(invalid)


def test_unsupported_improvements_cannot_be_activated_and_do_not_affect_battlescore_hash():
    config = analysis_settings.default_configuration()
    config.pop("configuration_hash", None)
    unsupported = deepcopy(config)
    unsupported["negative_achievements"]["rules"]["unspent_gold"]["enabled"] = True
    with pytest.raises(ValueError, match="Oro sin invertir"):
        analysis_settings.validate_configuration(unsupported)
    before = analysis_settings.engine_snapshot(config)["configuration_hash"]
    config["negative_achievements"]["rules"]["rough_start"]["thresholds"]["critical"] = 8
    after = analysis_settings.engine_snapshot(config)["configuration_hash"]
    assert before == after

