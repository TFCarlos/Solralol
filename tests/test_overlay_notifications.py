"""Recorded-shape Live Client event sequences; no real client is involved."""
from __future__ import annotations

import pytest

from app.services.overlay_alert_service import OverlayAlertTracker, structure_identity


CATALOG = {
    str(3000 + index): {"name": f"Completed {index}", "gold": {"purchasable": True, "total": 3000}, "tags": []}
    for index in range(1, 7)
}
CATALOG["3100"] = {"name": "Component", "gold": {"purchasable": True, "total": 500}, "tags": []}
CATALOG["3040"] = {"name": "Automatic upgrade", "gold": {"purchasable": False, "total": 3000}, "tags": []}


def frame(time, events=(), items=(), *, mode="CLASSIC", version="", local_team="ORDER"):
    return {"game_time": time, "game_mode": mode, "game_version": version, "local_team": local_team,
            "game_events": list(events), "all_players": [
                {"riotId": "Swain#EUW", "championName": "Swain", "team": "CHAOS",
                 "items": [{"itemID": int(item)} for item in items]},
            ]}


def event(ident, name, time, **fields):
    return {"EventID": ident, "EventName": name, "EventTime": time, **fields}


def test_empty_purchase_duration_deduplication_and_new_purchase_after_sale():
    tracker = OverlayAlertTracker(CATALOG)
    assert tracker.update(frame(100, items=(3001,))) == []  # first inventory is a baseline
    bought = tracker.update(frame(102, items=(3001, 3002, 3100, 3040)))
    assert len(bought) == 1 and bought[0]["item_id"] == "3002"
    assert bought[0]["champion"] == "Swain" and bought[0]["side"] == "enemy"
    assert tracker.update(frame(104, items=(3001, 3002, 3100, 3040))) == bought
    assert tracker.update(frame(110, items=(3001, 3002, 3100, 3040))) == []
    tracker.update(frame(112, items=(3001, 3100)))
    assert tracker.update(frame(114, items=(3001, 3002, 3100))) == []  # ambiguous reappearance
    assert [row["item_id"] for row in tracker.update(frame(116, items=(3001, 3002, 3003, 3100)))] == ["3003"]


def test_objective_early_and_final_countdown_are_distinct_lifecycles():
    tracker = OverlayAlertTracker(CATALOG)
    assert tracker.update(frame(239)) == []
    early = tracker.update(frame(240))
    assert len(early) == 1 and early[0]["objective"] == "dragon" and early[0]["remaining"] == 60
    assert tracker.update(frame(248)) == []
    assert tracker.update(frame(280)) == []
    final = tracker.update(frame(290))
    assert len(final) == 1 and final[0]["persistent"] and final[0]["remaining"] == 10
    assert final[0]["key"] != early[0]["key"]
    assert tracker.update(frame(299))[0]["remaining"] == 1
    assert tracker.update(frame(300)) == []  # expiry makes no claim of confirmed spawn


def test_objective_rules_do_not_leak_into_other_maps_or_modes():
    assert OverlayAlertTracker(CATALOG).update(frame(290, mode="ARAM")) == []
    other_map = frame(290)
    other_map["map_number"] = 12
    assert OverlayAlertTracker(CATALOG).update(other_map) == []


@pytest.mark.parametrize("structure,lane,owner", [
    ("Barracks_T1_L1", "TOP", "ORDER"), ("Barracks_T1_C1", "MID", "ORDER"),
    ("Barracks_T1_R1", "BOT", "ORDER"), ("Barracks_T2_L1", "TOP", "CHAOS"),
    ("Barracks_T2_C1", "MID", "CHAOS"), ("Barracks_T2_R1", "BOT", "CHAOS"),
])
def test_inhibitor_owner_and_lane_use_stable_structure_id(structure, lane, owner):
    assert structure_identity(structure, "inhibitor")[1:3] == (owner, lane)
    assert structure_identity("Barracks_T1_L2", "inhibitor") is None


def test_inhibitor_soon_event_anchors_countdown_and_respawn_confirms_end():
    tracker = OverlayAlertTracker(CATALOG)
    killed = event(10, "InhibKilled", 400, InhibKilled="Barracks_T2_C1")
    soon = event(11, "InhibRespawningSoon", 685, InhibRespawningSoon="Barracks_T2_C1")
    respawn = event(12, "InhibRespawned", 700, InhibRespawned="Barracks_T2_C1")
    assert tracker.update(frame(400, (killed,))) == []
    early = tracker.update(frame(685, (killed, soon)))
    assert len(early) == 1 and early[0]["name"] == "Inhibidor de MID"
    assert early[0]["side"] == "enemy" and early[0]["remaining"] == 15
    final = tracker.update(frame(690, (killed, soon)))
    assert final[0]["persistent"] and final[0]["remaining"] == 10
    assert tracker.update(frame(700, (killed, soon, respawn))) == []
    second = event(13, "InhibKilled", 750, InhibKilled="Barracks_T2_C1")
    again = event(14, "InhibRespawningSoon", 1035, InhibRespawningSoon="Barracks_T2_C1")
    rows = tracker.update(frame(1040, (killed, soon, respawn, second, again)))
    assert rows[0]["persistent"] and rows[0]["remaining"] == 10
    assert rows[0]["key"] != final[0]["key"]


def test_nexus_turrets_are_distinct_and_patch_gated():
    left = event(20, "TurretKilled", 500, TurretKilled="Turret_T1_C_02_A")
    right = event(21, "TurretKilled", 502, TurretKilled="Turret_T2_C_01_A")
    assert structure_identity("Turret_T1_C_03_A", "nexus_turret") is None
    unknown = OverlayAlertTracker(CATALOG)
    assert unknown.update(frame(670, (left, right))) == []
    tracker = OverlayAlertTracker(CATALOG)
    rows = tracker.update(frame(670, (left, right), version="26.20.1"))
    assert {(row["lane"], row["side"]) for row in rows} == {("TOP", "ally"), ("BOT", "enemy")}
    assert len({row["key"] for row in rows}) == 2
    rows = tracker.update(frame(672, (left, right), version="26.20.1"))
    assert len(rows) == 2 and all(row["persistent"] for row in rows)
    assert tracker.update(frame(682, (left, right), version="26.20.1")) == []


def test_countdown_priority_keeps_multiple_objectives_ahead_of_purchases():
    tracker = OverlayAlertTracker(CATALOG)
    dragon = event(1, "DragonKill", 900, KillerName="Swain#EUW")
    inhibitor = event(2, "InhibKilled", 800, InhibKilled="Barracks_T1_L1")
    soon = event(3, "InhibRespawningSoon", 1185, InhibRespawningSoon="Barracks_T1_L1")
    tracker.update(frame(1188, (dragon, inhibitor, soon)))
    rows = tracker.update(frame(1190, (dragon, inhibitor, soon), items=(3001, 3002)))
    assert len(rows) == 3
    assert sum(bool(row.get("persistent")) for row in rows) == 3  # dragon, baron, inhibitor
    assert all(row["kind"] != "purchase" for row in rows)
    later = tracker.update(frame(1200, (dragon, inhibitor, soon), items=(3001, 3002)))
    assert [row["kind"] for row in later] == ["purchase", "purchase"]


def test_changed_objective_deadline_replaces_old_notice_without_duplicate():
    tracker = OverlayAlertTracker(CATALOG)
    early = tracker.update(frame(240))[0]
    killed = event(30, "DragonKill", 245, KillerName="Swain#EUW")
    assert tracker.update(frame(246, (killed,))) == []
    later = tracker.update(frame(485, (killed,)))
    assert len(later) == 1 and later[0]["key"] != early["key"]
    assert later[0]["remaining"] == 60


def test_missing_inventory_gap_does_not_fabricate_purchase():
    tracker = OverlayAlertTracker(CATALOG)
    tracker.update(frame(100, items=(3001,)))
    assert tracker.update(frame(110, items=(3001, 3002))) == []
    assert [row["item_id"] for row in tracker.update(frame(112, items=(3001, 3002, 3003)))] == ["3003"]


def test_inhibitor_soon_event_can_recover_after_missing_destruction_history():
    tracker = OverlayAlertTracker(CATALOG)
    soon = event(50, "InhibRespawningSoon", 685, InhibRespawningSoon="Barracks_T1_R1")
    alert = tracker.update(frame(690, (soon,)))[0]
    assert alert["persistent"] and alert["lane"] == "BOT" and alert["side"] == "ally"
