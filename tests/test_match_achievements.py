from __future__ import annotations

import json
import pytest
from backend import analysis_settings
from backend.match_achievements import ACHIEVEMENT_REGISTRY, default_achievement_settings, evaluate_match_achievements


def _evaluate(player, *, participants=None, events=None, frames=None, duration=1800, score=None, settings=None, timeline=True):
    return evaluate_match_achievements(participants or [player], events or [], frames or [], duration,
        score or {"participants": []}, settings or {**default_achievement_settings(), "show_unearned": True}, timeline)


def _item(result, achievement_id):
    return next(row for row in result["items"] if row["id"] == achievement_id)


def test_registry_contains_all_nineteen_current_achievements():
    assert len(ACHIEVEMENT_REGISTRY) == 19
    assert len({row["id"] for row in ACHIEVEMENT_REGISTRY}) == 19


def test_damage_sponge_uses_battlescore_useful_damage_and_retains_partial_zero():
    player = {"participantId": 1, "local": True, "side": "allied"}
    result = _evaluate(player, score={"participants": [{"participantId": 1, "usefulDamageReceived": 0,
        "componentAvailability": {"useful_damage": "partial"}}]})
    achievement = _item(result, "damage_sponge")
    assert achievement["value"] == 0
    assert achievement["coverage"] == "partial"
    assert achievement["tier"] == "Sin medalla"


def test_missing_damage_sponge_is_unavailable_not_zero():
    player = {"participantId": 1, "local": True, "side": "allied"}
    achievement = _item(_evaluate(player), "damage_sponge")
    assert achievement["value"] is None
    assert achievement["coverage"] == "unavailable"
    assert achievement["tier"] == "No disponible"


def test_confirmed_zero_is_retained_and_unavailable_revives_are_not_fabricated():
    player = {"participantId": 1, "local": True, "side": "allied", "kills": 0, "deaths": 0, "assists": 0}
    result = _evaluate(player)
    assert _item(result, "executioner")["value"] == 0
    assert _item(result, "zombie")["value"] is None


def test_objective_steals_prefer_objectives_stolen_and_do_not_add_challenge_value():
    player = {"participantId": 1, "local": True, "side": "allied", "objectivesStolen": 0, "epicMonsterSteals": 2}
    assert _item(_evaluate(player), "scene_stealer")["value"] == 0
    player["objectivesStolen"] = None
    assert _item(_evaluate(player), "scene_stealer")["value"] == 2


def test_timeline_fallback_counts_only_explicit_steal_and_deduplicates():
    player = {"participantId": 1, "local": True, "side": "allied"}
    events = [
        {"id": "same", "timestamp": 100, "type": "ELITE_MONSTER_KILL", "killerId": 1, "monsterSubType": "DRAGON_STEAL"},
        {"id": "same", "timestamp": 100, "type": "ELITE_MONSTER_KILL", "killerId": 1, "monsterSubType": "DRAGON_STEAL"},
        {"id": "ordinary", "timestamp": 200, "type": "ELITE_MONSTER_KILL", "killerId": 1, "monsterSubType": "DRAGON"},
    ]
    assert _item(_evaluate(player, events=events), "scene_stealer")["value"] == 1


def test_cs_per_minute_uses_combined_match_counter_and_duration():
    player = {"participantId": 1, "local": True, "side": "allied", "cs": 155}
    assert _item(_evaluate(player, duration=29 * 60), "last_hit_master")["value"] == pytest.approx(155 / 29)


def test_last_frame_cs_fallback_sums_lane_and_jungle_once():
    player = {"participantId": 1, "local": True, "side": "allied"}
    frames = [{"participantId": 1, "timestamp": 1000, "minions": 120, "jungleMinions": 35}]
    assert _item(_evaluate(player, frames=frames, duration=29 * 60), "last_hit_master")["value"] == pytest.approx(155 / 29)


def test_fast_win_requires_win_and_uses_reverse_thresholds():
    player = {"participantId": 1, "local": True, "side": "allied", "win": False}
    assert _item(_evaluate(player, duration=1000), "fast_forward")["tier"] == "Sin medalla"
    player["win"] = True
    assert _item(_evaluate(player, duration=1000), "fast_forward")["tier"] == "Diamante"


def test_visibility_hides_unearned_but_keeps_earned_and_zero_that_meets_threshold():
    player = {"participantId": 1, "local": True, "side": "allied", "kills": 0}
    settings = default_achievement_settings()
    settings["show_unearned"] = False
    settings["thresholds"]["executioner"] = {"bronze": 0, "silver": 1, "gold": 2, "diamond": 3}
    rows = _evaluate(player, settings=settings)["items"]
    assert any(row["id"] == "executioner" and row["value"] == 0 and row["earned"] for row in rows)
    assert all(row["earned"] for row in rows)


def test_configuration_validates_medal_order_and_migrates_existing_file(tmp_path, monkeypatch):
    defaults = analysis_settings.default_configuration()
    bad = json.loads(json.dumps(defaults))
    bad.pop("configuration_hash", None)
    bad["achievements"]["thresholds"]["last_hit_master"] = {"bronze": 7, "silver": 5, "gold": 8, "diamond": 9}
    with pytest.raises(ValueError, match="Maestro del último golpe"):
        analysis_settings.validate_configuration(bad)
    old = json.loads(json.dumps(defaults))
    old.pop("configuration_hash", None)
    old.pop("achievements")
    old["rewards"]["gold_per_1000"] = 0.222
    path = tmp_path / "analysis_settings.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    monkeypatch.setattr(analysis_settings, "config_path", lambda: path)
    loaded = analysis_settings.load_configuration()
    assert loaded["rewards"]["gold_per_1000"] == 0.222
    assert len(loaded["achievements"]["thresholds"]) == 19
    assert path.with_suffix(".json.bak").exists()


def test_achievement_changes_do_not_invalidate_battlescore_configuration():
    original = analysis_settings.default_configuration()
    changed = json.loads(json.dumps(original))
    changed["achievements"]["show_unearned"] = True
    changed["achievements"]["thresholds"]["executioner"] = {"bronze": 5, "silver": 8, "gold": 99, "diamond": 100}
    assert analysis_settings.engine_snapshot(original)["configuration_hash"] == analysis_settings.engine_snapshot(changed)["configuration_hash"]



def test_all_medal_tiers_and_below_bronze_classify_from_configured_thresholds():
    base = {"participantId": 1, "local": True, "side": "allied", "kills": 0}
    settings = default_achievement_settings()
    settings["show_unearned"] = True
    settings["thresholds"]["executioner"] = {"bronze": 1, "silver": 2, "gold": 3, "diamond": 4}
    observed = []
    for value in (0, 1, 2, 3, 4):
        player = {**base, "kills": value}
        observed.append(_item(_evaluate(player, settings=settings), "executioner")["tier"])
    assert observed == ["Sin medalla", "Bronce", "Plata", "Oro", "Diamante"]


def test_integer_achievement_thresholds_reject_decimal_values():
    config = analysis_settings.default_configuration()
    config.pop("configuration_hash", None)
    config["achievements"]["thresholds"]["executioner"]["bronze"] = 1.5
    with pytest.raises(ValueError, match="deben ser enteros"):
        analysis_settings.validate_configuration(config)
