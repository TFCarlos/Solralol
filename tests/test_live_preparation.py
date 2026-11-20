from __future__ import annotations

from collections import Counter
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.services.enemy_inventory_tracker import EnemyInventoryTracker, normalized_inventory
from app.services.live_preparation_service import LivePreparationService
from app.services.live_recommendation_service import LiveRecommendationService
from backend.live_match import _item_catalog


@pytest.fixture
def catalog():
    return _item_catalog()


def enemy(ids=(), champion="Briar"):
    return {"championName": champion, "position": "JUNGLE", "items": [{"itemID": int(i), "count": 1, "slot": slot} for slot, i in enumerate(ids)]}


def update(tracker, time, ids=(), *, champion="Briar", session="match", fresh=True):
    return tracker.update(session, time, [("chaos:participant:7", enemy(ids, champion))], fresh=fresh)[0]


def test_first_observation_uses_game_clock_and_purchase_resets(catalog):
    tracker = EnemyInventoryTracker(catalog)
    assert update(tracker, 120, ["1055"])["elapsedSeconds"] == 0
    assert update(tracker, 210, ["1055"])["elapsedSeconds"] == 90
    assert update(tracker, 240, ["1055"])["state"] == "warning"
    bought = update(tracker, 300, ["1055", "1036"])
    assert bought["elapsedSeconds"] == 0 and bought["lastInferredShopAt"] == 300
    assert bought["origin"] == "inferred_purchase" and bought["visibilityVerified"] is False
    assert "chaos" not in bought["participantId"]
    assert update(tracker, 310, ["1055", "1036"])["elapsedSeconds"] == 10


@pytest.mark.parametrize("before,after", [
    (["1055"], ["1055", "2422"]),  # Magical Footwear, no enemy full-rune feed needed.
    (["3865"], ["3866"]),
    (["3866"], ["3867"]),
    (["3867"], ["3869"]),
    (["3003"], ["3040"]),
    (["3004"], ["3042"]),
    (["3119"], ["3121"]),
    (["1036", "2003"], ["1036"]),
    (["1036", "1036", "2003"], ["2003", "1036", "1036"]),
])
def test_automatic_progression_consumption_and_reordering_do_not_reset(catalog, before, after):
    tracker = EnemyInventoryTracker(catalog)
    update(tracker, 120, before)
    row = update(tracker, 360, after)
    assert row["elapsedSeconds"] == 240 and row["lastInferredShopAt"] is None
    assert row["state"] == "critical"


def test_automatic_support_upgrade_plus_real_purchase_resets(catalog):
    tracker = EnemyInventoryTracker(catalog)
    update(tracker, 120, ["3865"])
    row = update(tracker, 300, ["3866", "1001"])
    assert row["lastInferredShopAt"] == 300 and row["state"] == "normal"


def test_stale_missing_incomplete_duplicate_and_gap_data_cannot_invent_visit(catalog):
    tracker = EnemyInventoryTracker(catalog)
    update(tracker, 120, ["1055"])
    update(tracker, 150, ["1055", "1036"], fresh=False)
    row = update(tracker, 160, ["1055", "1036"])
    assert row["elapsedSeconds"] == 40 and row["classification"] == "gap_baseline"
    assert update(tracker, 160, ["1055", "1036", "1001"])["lastInferredShopAt"] is None
    tracker.update("match", 170, [("chaos:participant:7", {"championName": "Briar", "items": None})])
    assert update(tracker, 180, ["1036"])["lastInferredShopAt"] is None
    tracker.mark_gap()
    assert update(tracker, 190, ["1036", "1001"])["lastInferredShopAt"] is None
    assert normalized_inventory([{"itemID": "bad"}]) is None
    assert normalized_inventory([{"itemID": 1036, "count": 2}]) == Counter({"1036": 2})
    assert tracker.classify(Counter({"999999": 1}), Counter({"1036": 1}), "Briar") == "unverified_change"


def test_ornn_field_crafting_is_not_a_base_visit(catalog):
    tracker = EnemyInventoryTracker(catalog)
    update(tracker, 120, ["1055"], champion="Ornn")
    row = update(tracker, 400, ["1055", "1036"], champion="Ornn")
    assert row["lastInferredShopAt"] is None and row["classification"] == "field_crafting_unverified"
    assert row["elapsedSeconds"] == 280


def test_session_restart_rewind_invalid_clock_and_independent_players(catalog):
    tracker = EnemyInventoryTracker(catalog)
    update(tracker, 120, ["1055"])
    assert update(tracker, 400, ["1055"])["state"] == "critical"
    assert update(tracker, 401, ["1055", "1036"])["state"] == "normal"
    assert update(tracker, 10, ["1055"])["elapsedSeconds"] == 0
    assert update(tracker, -1)["elapsedSeconds"] is None
    assert update(tracker, 8, session="next")["elapsedSeconds"] == 0
    tracker.update("next", 12, [("enemy-A", enemy()), ("enemy-B", enemy(champion="Ahri"))])
    rows = tracker.update("next", 130, [("enemy-A", enemy(["1036"])), ("enemy-B", enemy(champion="Ahri"))])
    assert [row["elapsedSeconds"] for row in rows] == [0, 118]
    assert rows[0]["participantId"] != rows[1]["participantId"]


def session(champion="Briar", role="JUNGLE", inventory=(), keystone=8005):
    players = {"self": {"champion_name": champion, "role": role, "team": "ORDER", "items": list(inventory), "runes": {"keystone": {"id": keystone}}, "current_gold": 900, "level": 10, "kills": 2, "deaths": 1, "assists": 2},
               "enemy": {"champion_name": "Aatrox", "role": "TOP", "team": "CHAOS", "items": [], "kills": 4, "deaths": 0, "assists": 1}}
    return {"session_id": "test", "game_mode": "CLASSIC", "duration": 900, "local_player_key": "self", "players": players, "snapshots": [{"time": 900, "players": players}]}


def test_rank_reuses_actual_engine_scores_role_and_skill_order(catalog):
    service = LivePreparationService(catalog)
    match = session()
    profile, skill = service.context(match)
    expected = service.engine.analyze(match, profile_override=profile)["recommendations"][:3]
    result = service.rank(match)
    rows = result["recommendations"]
    assert len(rows) >= 3
    assert [row["score"] for row in rows] == sorted([row["score"] for row in rows], reverse=True)
    assert [(r["id"], r["score"]) for r in rows[:3]] == [(r["id"], r["score"]) for r in expected]
    assert all(service.engine.available(row["id"]) for row in rows)
    assert all(service.engine.stat(row["id"], "ability_power") == 0 for row in rows)
    assert skill["status"] == "available" and len(skill["order"]) == 18 and skill["role"] == "jungle"
    assert result["skillOrder"] == skill


def test_runes_select_evidenced_build_and_skill_variant_instead_of_arbitrary_scores(catalog):
    class Repository:
        def consultar(self, champion, role, rank):
            assert (champion, role, rank) == ("Briar", "jungle", "emerald_plus")
            return SimpleNamespace(datos={"runes": [
                {"keystone_id": 8005, "build": ["Hoja del rey arruinado"], "skill_order": {"order": ["W", "E", "Q"]}},
                {"keystone_id": 8010, "build": ["Cuchilla negra"], "skill_order": {"order": ["Q", "W", "E"]}},
            ]})
    service = LivePreparationService(catalog, repository=Repository())
    pta, pta_skill = service.context(session(keystone=8005))
    conqueror, conq_skill = service.context(session(keystone=8010))
    assert pta["most_played_build"] != conqueror["most_played_build"]
    assert pta_skill["order"] != conq_skill["order"]
    assert pta_skill["runeMatched"] and conq_skill["runeMatched"]
    item = {**catalog["3153"], **service.engine.strict["3153"], "tier": "Legendary"}
    pta_score = service.engine._score_candidate("3153", item, pta, "Briar", [], [], .5, "11")
    conq_score = service.engine._score_candidate("3153", item, conqueror, "Briar", [], [], .5, "11")
    assert pta_score["score"] > conq_score["score"]


def test_enemy_composition_and_own_components_influence_legacy_scoring(catalog):
    service = LivePreparationService(catalog)
    match = session()
    profile, _ = service.context(match)
    item = {**catalog["3071"], **service.engine.strict["3071"], "tier": "Legendary"}
    base = service.engine._score_candidate("3071", item, profile, "Briar", [], [], .5, "11")
    counter = service.engine._score_candidate("3071", item, profile, "Briar", ["1036"], [{"champion": "Malphite", "signals": [{"kind": "armor"}], "weight": 1.0}], .5, "11")
    assert counter["score"] > base["score"] and counter["invested"] > base["invested"]
    assert "Malphite" in " ".join(counter["responses"])


def test_shields_and_burst_reuse_local_riot_metadata_and_existing_counter_scoring(catalog, monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda *_args, **_kwargs: pytest.fail("No se permiten descargas al recomendar"))
    service = LivePreparationService(catalog)
    match = session()
    players = match["players"]
    players["enemy"]["champion_name"] = "Lulu"
    result = service.engine.analyze(match)
    assert any(signal["kind"] == "shielding" and not signal["observed"] for signal in result["threats"][0]["signals"])
    players["enemy"]["champion_name"] = "Zed"
    result = service.engine.analyze(match)
    assert any(signal["kind"] == "burst" for signal in result["threats"][0]["signals"])
    # Shield destruction in an enemy tooltip must not be mistaken for a shield grant.
    players["enemy"]["champion_name"] = "Renekton"
    result = service.engine.analyze(match)
    assert not any(signal["kind"] == "shielding" for signal in result["threats"][0]["signals"])


def test_first_purchase_respects_recipe_affordability_owned_multisets_and_slots(catalog):
    engine = LiveRecommendationService(catalog)
    service = LivePreparationService(catalog, engine=engine)
    row = {"id": "3100", "name": engine.name("3100"), "score": 40, "cost": 2900, "reasons": [], "responses": []}
    affordable = service.purchases([row], {"items": []}, 900, "CLASSIC")[0]["nextPurchase"]
    assert affordable["status"] == "buy" and affordable["cost"] <= 900
    assert affordable["id"] != "3100"
    waiting = service.purchases([row], {"items": []}, 0, "CLASSIC")[0]["nextPurchase"]
    assert waiting["status"] == "save" and waiting["missing"] > 0
    owned = service.purchases([row], {"items": [{"itemID": 3057}]}, 1000, "CLASSIC")[0]["nextPurchase"]
    assert owned.get("id") != "3057"
    assert service.purchases([row], {"items": [{"itemID": 3100}]}, 9999, "CLASSIC") == []
    unknown = service.purchases([row], {"items": []}, None, "CLASSIC")[0]["nextPurchase"]
    assert unknown["status"] == "unknown"
    stacked = [{"itemID": 2003, "count": 5}]
    assert engine.inventory_slots(stacked) == 1
    assert engine.inventory_slots(stacked + [{"itemID": 3340}]) == 1
    assert engine.inventory_slots(stacked + [{"itemID": 99999}]) == 2
    component_full = [{"itemID": i} for i in (3057, 1052, 1052, 1026, 1001, 2003)]
    bought = service.purchases([row], {"items": component_full}, 9999, "CLASSIC")[0]["nextPurchase"]
    assert bought["status"] == "buy" and bought["id"] == "3100"
    magical = engine.purchase("3111", ["2422"], 1000)
    assert magical.get("id") != "1001"
    assert engine._recipe("3111", ["2422"])[0] == engine.cost("3111") - engine.cost("1001")


def test_ranked_purchase_cards_advance_on_completed_item_and_restore_after_sale(catalog):
    service = LivePreparationService(catalog)
    ranked = service.rank(session())["recommendations"]
    assert len(ranked) > 3
    first = service.purchases(ranked, {"items": []}, 900, "CLASSIC")
    assert [row["id"] for row in first] == [row["id"] for row in ranked[:3]]
    completed = ranked[0]["id"]
    after = service.purchases(ranked, {"items": [{"itemID": int(completed)}]}, 900, "CLASSIC")
    assert [row["id"] for row in after] == [row["id"] for row in ranked[1:4]]
    assert all(row["nextPurchase"]["target"] == row["id"] for row in after)
    assert [row["id"] for row in service.purchases(ranked, {"items": []}, 900, "CLASSIC")] == [row["id"] for row in first]
    assert [row["id"] for row in service.purchases(ranked, {"items": [{"itemID": int(completed), "count": 0}]}, 900, "CLASSIC")] == [row["id"] for row in first]


def test_component_changes_purchase_icon_without_hiding_completed_target(catalog):
    service = LivePreparationService(catalog)
    row = {"id": "3100", "name": service.engine.name("3100"), "score": 40}
    before = service.purchases([row], {"items": []}, 2000, "CLASSIC")[0]
    after = service.purchases([row], {"items": [{"itemID": 3057}]}, 2000, "CLASSIC")[0]
    assert before["id"] == after["id"] == "3100"
    assert before["nextPurchase"]["id"] != after["nextPurchase"]["id"]


def test_transformed_completed_item_excludes_base_recommendation(catalog):
    service = LivePreparationService(catalog)
    row = {"id": "3003", "name": service.engine.name("3003"), "score": 40}
    assert service.purchases([row], {"items": [{"itemID": 3040}]}, 900, "CLASSIC") == []


def test_missing_champion_role_and_unsupported_mode_fail_explicitly(catalog):
    service = LivePreparationService(catalog)
    assert service.rank(session(champion="NoSuchChampion"))["recommendations"] == []
    fallback = service.context(session(role="UNKNOWN"))[1]
    assert fallback["status"] == "available" and fallback["roleFallback"] is True
    match = session(); match["game_mode"] = "CHERRY"
    assert service.rank(match)["recommendations"] == []
    assert service.engine.profile("MonkeyKing")["character"] == "Wukong"
    assert service.engine.profile("Nunu")["character"] == "Nunu & Willump"


@pytest.mark.parametrize("label", ["JUNGLE", "Jungla", "Jungle", "JG", "JGL"])
def test_briar_skill_matches_local_analysis_for_role_aliases(catalog, label):
    from app.services.preparador_datos_campeon import combinar_perfil
    from app.services.repositorio_campeones import RepositorioCampeones

    service = LivePreparationService(catalog)
    local = RepositorioCampeones().consultar("Briar", "jungle", "emerald_plus")
    expected = combinar_perfil(local.perfil, local.datos)["skill_order"]["order"]
    skill = service.context(session(role=label))[1]
    assert skill["status"] == "available"
    assert skill["role"] == "jungle"
    assert len(skill["order"]) == 18
    assert skill["order"] == expected


def test_local_analysis_update_replaces_previous_missing_skill(catalog, tmp_path):
    from app.services.repositorio_campeones import RepositorioCampeones

    source = RepositorioCampeones().obtener_campeon("Briar").datos
    repository = RepositorioCampeones(tmp_path)
    document = deepcopy(source)
    document["ranks"]["emerald_plus"]["jungle"].pop("skill_order", None)
    for page in document["ranks"]["emerald_plus"]["jungle"].get("runes", []):
        page.pop("skill_order", None)
    repository.guardar("Briar", document)
    service = LivePreparationService(catalog, repository=repository)
    before = service.context(session())[1]
    assert before["roleFallback"] is True
    document["ranks"]["emerald_plus"]["jungle"]["skill_order"] = source["ranks"]["emerald_plus"]["jungle"]["skill_order"]
    repository.guardar("Briar", document)
    after = service.context(session())[1]
    assert after["status"] == "available" and after["role"] == "jungle"
    assert after.get("roleFallback") is None


def test_briar_skill_equals_local_analysis_prepared_view(catalog):
    import json
    from _paths import DATA_DIR
    from app.services.analisis_local_service import AnalisisLocalService
    from app.services.catalogo_analisis_local import CatalogoAnalisisLocal
    from app.services.item_name_aliases import ITEM_NAME_ALIASES
    from app.services.repositorio_campeones import RepositorioCampeones
    from app.services.storage_manager import get_storage_manager

    items = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
    strict = json.loads((DATA_DIR / "legendary_items_strict.json").read_text(encoding="utf-8"))
    version = str(items.get("version") or "")
    analysis = AnalisisLocalService(
        CatalogoAnalisisLocal(items["items"], strict, ITEM_NAME_ALIASES, version),
        get_storage_manager().cache_dir / "champions", version,
    )
    stored = RepositorioCampeones().consultar("Briar", "jungle", "emerald_plus")
    prepared = analysis.cargar({**stored.perfil, "character": "Briar"}, "jungle", "emerald_plus", {}, lambda: False)
    live_skill = LivePreparationService(catalog).context(session(role="JUNGLE"))[1]
    assert live_skill["order"] == prepared["perfil"]["skill_order"]["order"]


def test_enemy_death_pauses_and_respawn_rebaselines_without_second_purchase(catalog):
    tracker = EnemyInventoryTracker(catalog)
    def observed(t, dead, items=("1055",), deaths=0):
        player = {**enemy(items), "isDead": dead, "scores": {"deaths": deaths}}
        return tracker.update("match", t, [("enemy-stable", player)])[0]

    assert observed(300, False)["elapsedSeconds"] == 0
    assert observed(390, False)["elapsedSeconds"] == 90
    death = observed(405, True, deaths=1)
    assert death["state"] == "dead" and death["elapsedSeconds"] == 105
    assert observed(430, True, ("1055", "1036"), 1)["elapsedSeconds"] == 105
    assert observed(430, True, ("1055", "1036"), 1)["state"] == "dead"
    reborn = observed(435, False, ("1055", "1036"), 1)
    assert reborn["elapsedSeconds"] == 0 and reborn["state"] == "normal"
    assert reborn["lastInferredShopAt"] is None and reborn["origin"] == "respawn_observed"
    assert observed(495, False, ("1055", "1036"), 1)["elapsedSeconds"] == 60
    assert observed(555, False, ("1055", "1036"), 1)["state"] == "warning"
    assert observed(675, False, ("1055", "1036"), 1)["state"] == "critical"
    assert observed(680, True, deaths=2)["state"] == "dead"
    assert observed(710, False, deaths=2)["elapsedSeconds"] == 0


def test_enemy_joining_dead_and_gap_respawn_are_observation_based(catalog):
    tracker = EnemyInventoryTracker(catalog)
    player = {**enemy(("1055",)), "isDead": True, "scores": {"deaths": 1}}
    dead = tracker.update("match", 420, [("enemy-stable", player)])[0]
    assert dead["state"] == "dead" and dead["elapsedSeconds"] is None
    tracker.mark_gap()
    player["isDead"] = False
    alive = tracker.update("match", 445, [("enemy-stable", player)])[0]
    assert alive["elapsedSeconds"] == 0 and alive["origin"] == "respawn_observed"
    tracker.mark_gap()
    player["scores"]["deaths"] = 2
    assert tracker.update("match", 500, [("enemy-stable", player)])[0]["elapsedSeconds"] == 0
    assert tracker.update("new-match", 5, [("enemy-stable", player)])[0]["elapsedSeconds"] == 0


def test_missed_short_death_uses_first_confirmed_alive_reading(catalog):
    tracker = EnemyInventoryTracker(catalog)
    player = {**enemy(("1055",)), "isDead": False, "scores": {"deaths": 0}}
    tracker.update("match", 300, [("enemy-stable", player)])
    player["scores"]["deaths"] = 1
    row = tracker.update("match", 360, [("enemy-stable", player)])[0]
    assert row["elapsedSeconds"] == 0 and row["origin"] == "respawn_observed"
