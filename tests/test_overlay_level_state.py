"""Live recall and ability recommendation state transitions."""

import pytest

from app.services.enemy_inventory_tracker import EnemyInventoryTracker
from app.services.overlay_level_state import PendingAbility, ability_ranks, next_ability
from app.services.settings_service import _validate_electron_settings

ORDER = ["Q", "W", "E", "Q", "Q", "R", "Q", "W"]


def ranks(q=0, w=0, e=0, r=0):
    return {slot: {"abilityLevel": value} for slot, value in zip("QWER", (q, w, e, r), strict=True)}


def test_level_up_highlight_appears_and_clears_after_spending():
    state = PendingAbility()
    assert state.update(4, ranks(2, 1, 1), ORDER) is None
    assert state.update(4, ranks(2, 1, 1), ORDER) is None
    assert state.update(5, ranks(2, 1, 1), ORDER) == "Q"
    assert state.update(5, ranks(3, 1, 1), ORDER) is None


def test_multiple_points_and_reconnect_without_false_notification():
    state = PendingAbility()
    state.update(3, ranks(1, 1, 1), ORDER)
    assert state.update(5, ranks(1, 1, 1), ORDER) == "Q"
    assert state.update(5, ranks(2, 1, 1), ORDER) == "Q"
    assert state.update(5, ranks(3, 1, 1), ORDER) is None
    state.reset()
    assert state.update(12, ranks(5, 3, 2, 1), ORDER) is None


def test_reconnect_with_unspent_point_uses_observed_ranks():
    state = PendingAbility()
    assert state.update(6, ranks(3, 1, 1), ORDER) == "R"
    assert state.update(6, ranks(3, 1, 1, 1), ORDER) is None


def test_deviation_selects_earliest_unmet_legal_rank():
    state = PendingAbility()
    # The player bought W twice, so a simple sequence[allocated] would be wrong.
    assert state.update(5, ranks(1, 2, 1), ORDER) == "Q"
    assert state.update(5, ranks(2, 2, 1), ORDER) is None


def test_skill_legality_and_multiple_pending_points():
    state = PendingAbility()
    assert state.update(5, ranks(3, 0, 0), ORDER) == "W"
    assert state.update(5, ranks(3, 1, 0), ORDER) == "E"
    assert state.update(5, ranks(3, 1, 1), ORDER) is None
    assert next_ability(["R", "Q"], {"Q": 0, "W": 0, "E": 0, "R": 0}, 1) == "Q"
    assert next_ability(["Q"] * 6 + ["W"], {"Q": 5, "W": 0, "E": 0, "R": 0}, 18) == "W"
    assert state.update(1, ranks(), ["R", "Q"], "Jayce") == "Q"


def test_untrusted_rank_and_missing_sequence_are_silent():
    assert ability_ranks({"Q": {"abilityLevel": 1}}) is None
    assert next_ability(["-"], {slot: 0 for slot in "QWER"}, 1) is None
    state = PendingAbility()
    state.update(1, ranks(), None)
    assert state.update(2, ranks(1), None) is None


def test_recall_source_pauses_on_death_and_resets_after_respawn():
    tracker = EnemyInventoryTracker({})
    def enemy(dead, deaths=0):
        return [("enemy-id", {"championName": "Ahri", "isDead": dead,
                              "scores": {"deaths": deaths}, "items": []})]
    first = tracker.update("session", 10, enemy(False))[0]
    dead = tracker.update("session", 30, enemy(True, 1))[0]
    still_dead = tracker.update("session", 40, enemy(True, 1))[0]
    alive = tracker.update("session", 50, enemy(False, 1))[0]
    assert first["origin"] == "first_observation"
    assert dead["state"] == "dead"
    assert still_dead["elapsedSeconds"] == dead["elapsedSeconds"]
    assert alive["origin"] == "respawn_observed"
    assert alive["elapsedSeconds"] == 0
    assert alive["lastInferredShopAt"] is None


def test_new_overlay_settings_validate_bounds():
    assert _validate_electron_settings({"overlay_panels": {"recall": True, "ability": True},
                                        "overlay_ability_hud_anchor": {"x": 0.5, "y": 0.89},
                                        "overlay_ability_slot_spacing": 47})["overlay_ability_slot_spacing"] == 47
    with pytest.raises(ValueError):
        _validate_electron_settings({"overlay_ability_slot_spacing": 120})
    with pytest.raises(ValueError):
        _validate_electron_settings({"overlay_ability_hud_anchor": {"x": -1, "y": 0.89}})
