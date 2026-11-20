from __future__ import annotations

import pytest

from app.services.live_match_tracker import LiveMatchTracker
from app.services.overlay_alert_service import OverlayAlertTracker
from app.services.overlay_sound_service import OverlaySoundService
from backend.live_match import LiveMatchRuntime, _item_catalog, calculate_kill_participation
from app.services.live_event_normalizer import normalize_live_event


def sample(game_time: float = 20) -> dict:
    players = [
        {"championName": "Ahri", "team": "ORDER", "riotId": "Player#EUW", "level": 5,
         "scores": {"kills": 1, "deaths": 0, "assists": 2, "creepScore": 30, "wardScore": 1},
         "runes": {"keystone": {"id": 8005, "displayName": "Press the Attack"}},
         "items": [{"itemID": 1056, "displayName": "Doran's Ring"}]},
        {"championName": "Garen", "team": "CHAOS", "riotId": "Enemy#EUW", "scores": {"kills": 0, "deaths": 1, "assists": 0, "creepScore": 25, "wardScore": 0}, "items": []},
    ]
    return {"game_mode": "CLASSIC", "game_time": game_time, "local_team": "ORDER",
            "local_player": players[0], "all_players": players, "enemies": players[1:],
            "local_live_stats": {"currentGold": 450},
            "game_events": [{"EventID": 3, "EventTime": game_time, "EventName": "ChampionKill",
                             "KillerName": "Player#EUW", "VictimName": "Enemy#EUW"},
                            {"EventID": 4, "EventTime": game_time, "EventName": "DragonKill",
                             "KillerName": "Enemy#EUW", "DragonType": "Air"}]}


def runtime() -> LiveMatchRuntime:
    instance = LiveMatchRuntime.__new__(LiveMatchRuntime)
    import threading
    instance.lcu = type("LCU", (), {"is_connected": lambda self: True})()
    instance._gameflow_phase = lambda: "InProgress"
    instance.game = type("Game", (), {"get_live_snapshot": lambda self: sample()})()
    instance.items = _item_catalog()
    instance.tracker = LiveMatchTracker(instance.items, persist=False)
    instance.alert_tracker = OverlayAlertTracker({})
    instance.settings_service = None
    instance.sound_service = OverlaySoundService(enabled=False)
    instance._played_sound_alerts = set()
    import time
    instance._sound_settings_checked_at = time.monotonic()
    instance._recommendation_pool = None
    instance._recommendation_future = None
    instance._recommendation_signature = None
    instance._recommendation_requested_at = 0.0
    instance._recommendations = []
    instance._recommendation_session_id = None
    instance._schedule_recommendations = lambda *_args: None
    instance.recordings = None
    instance.on_completed = None
    instance.lock = threading.RLock()
    instance.state = {"state": "connected", "connected": True, "telemetry": "unavailable", "snapshot": None,
                      "sessionId": None, "lastUpdated": None, "message": "", "source": "live"}
    instance.failures = 0
    instance.stop_event = threading.Event()
    instance._draft_context = {"connected": True, "phase": "InProgress", "session": None}
    return instance


def test_overlay_sound_follows_alert_instances_not_snapshot_refreshes():
    subject = runtime()
    played = []
    subject.sound_service.play_dragon_spawn = lambda: played.append("dragon")
    subject.sound_service.play_objective_spawn = lambda: played.append("objective")
    subject.sound_service.play_enemy_buy = lambda: played.append("enemy_buy")
    dragon = {"key": "objective:dragon:300:early", "kind": "objective", "objective": "dragon"}
    purchase = {"key": "purchase:enemy:3001:250:0", "kind": "purchase", "side": "enemy"}

    subject._update_overlay_sounds([dragon])
    subject._update_overlay_sounds([dragon])
    subject._update_overlay_sounds([])
    subject._update_overlay_sounds([dragon, purchase])
    assert played == ["dragon", "enemy_buy"]

    subject._update_overlay_sounds([{"key": "purchase:enemy:3002:250:0", "kind": "purchase", "side": "enemy"}])
    assert played == ["dragon", "enemy_buy", "enemy_buy"]
    subject.sound_service.close()


def test_runtime_tracks_active_game_and_deduplicates_repeated_event_snapshots():
    subject = runtime()
    subject._tick()
    first = subject.snapshot()
    subject.game.get_live_snapshot = lambda: sample(22)
    subject._tick()
    second = subject.snapshot()
    assert first["state"] == "active"
    assert first["snapshot"]["localTeam"] == "ORDER"
    assert "riotId" not in first["snapshot"]["localPlayer"]
    assert "summonerName" not in first["snapshot"]["players"][0]
    assert first["snapshot"]["events"][0]["KillerChampion"] == "Ahri"
    assert first["snapshot"]["events"][0]["VictimChampion"] == "Garen"
    assert first["snapshot"]["events"][0]["KillerActorType"] == "champion"
    assert first["snapshot"]["events"][1]["EventTeam"] == "CHAOS"
    assert first["snapshot"]["localPlayer"]["runes"]["keystone"]["id"] == 8005
    assert "KillerName" not in first["snapshot"]["events"][0]
    assert second["snapshot"]["players"][0]["items"][0]["itemID"] == 1056
    session = subject.tracker.get_live_session()
    assert len(session["seen_event_ids"]) == 2
    subject.tracker.finish(persist=False)


def test_pending_ability_uses_observed_ranks_and_ignores_initial_level():
    subject = runtime()
    subject._skill_order = {"status": "available", "order": ["Q", "W", "E", "Q", "Q", "R"]}
    def reading(level, q, game_time):
        value = sample(game_time)
        value["local_live_stats"]["level"] = level
        value["local_abilities"] = {slot: {"abilityLevel": rank} for slot, rank in
                                    zip("QWER", (q, 1, 1, 0), strict=True)}
        return value
    subject.game.get_live_snapshot = lambda: reading(4, 2, 20)
    subject._tick()
    assert subject.snapshot()["snapshot"]["pendingAbility"] is None
    subject.game.get_live_snapshot = lambda: reading(5, 2, 22)
    subject._tick()
    assert subject.snapshot()["snapshot"]["pendingAbility"]["slot"] == "Q"
    subject.game.get_live_snapshot = lambda: reading(5, 3, 24)
    subject._tick()
    assert subject.snapshot()["snapshot"]["pendingAbility"] is None
    subject.tracker.finish(persist=False)


def test_enemy_shop_tracking_runs_in_authoritative_pipeline_without_extra_polls():
    subject = runtime()
    subject.game.get_live_snapshot = lambda: sample(120)
    subject._tick()
    first = subject.snapshot()["snapshot"]["enemyShopTimers"][0]
    changed = sample(360)
    subject.game.get_live_snapshot = lambda: changed
    subject._tick()
    critical = subject.snapshot()["snapshot"]["enemyShopTimers"][0]
    assert critical["participantId"] == first["participantId"]
    assert critical["elapsedSeconds"] == 240 and critical["state"] == "critical"
    changed["game_time"] = 362
    changed["all_players"][1]["items"] = [{"itemID": 1036}]
    subject._tick()
    bought = subject.snapshot()["snapshot"]["enemyShopTimers"][0]
    assert bought["elapsedSeconds"] == 0 and bought["lastInferredShopAt"] == 362
    assert "Enemy#EUW" not in str(bought)
    subject._finish()
    assert not subject.enemy_inventory_tracker.players


def test_enemy_respawn_uses_existing_playerlist_life_state():
    subject = runtime()
    frame = sample(300)
    frame["all_players"][1]["isDead"] = False
    subject._update(frame)
    frame["game_time"] = 390
    subject._update(frame)
    frame["game_time"] = 405
    frame["all_players"][1]["isDead"] = True
    frame["all_players"][1]["scores"]["deaths"] = 2
    subject._update(frame)
    dead = subject.snapshot()["snapshot"]["enemyShopTimers"][0]
    assert dead["state"] == "dead" and dead["elapsedSeconds"] == 105
    frame["game_time"] = 430
    frame["all_players"][1]["items"] = [{"itemID": 1036}]
    subject._update(frame)
    assert subject.snapshot()["snapshot"]["enemyShopTimers"][0]["elapsedSeconds"] == 105
    frame["game_time"] = 435
    frame["all_players"][1]["isDead"] = False
    subject._update(frame)
    reborn = subject.snapshot()["snapshot"]["enemyShopTimers"][0]
    assert reborn["elapsedSeconds"] == 0 and reborn["state"] == "normal"
    assert reborn["participantId"] == dead["participantId"]
    subject.tracker.finish(persist=False)


def test_updated_local_skill_file_invalidates_live_recommendation_signature(tmp_path):
    from concurrent.futures import Future
    from types import SimpleNamespace

    subject = runtime()
    subject._schedule_recommendations = LiveMatchRuntime._schedule_recommendations.__get__(subject)
    source = tmp_path / "briar.json"
    source.write_text("first", encoding="utf-8")
    subject._preparation_service = SimpleNamespace(repository=SimpleNamespace(ruta=lambda _: source))
    class Pool:
        def __init__(self): self.requests = []
        def submit(self, _callback, _context):
            future = Future()
            self.requests.append(future)
            return future
    pool = Pool()
    subject._recommendation_pool = pool
    frame = sample(120)
    subject.tracker.start(frame)
    match = subject.tracker.session
    subject._schedule_recommendations(match, frame)
    assert len(pool.requests) == 1
    pool.requests[0].set_result({"recommendations": [], "skillOrder": {"status": "unavailable", "order": []}})
    source.write_text("second version", encoding="utf-8")
    subject._skill_revision_checked_at = 0
    subject._schedule_recommendations(match, frame)
    assert len(pool.requests) == 2
    subject.tracker.finish(persist=False)


def test_recommendation_scoring_ignores_gold_only_changes_and_rejects_obsolete_results():
    from concurrent.futures import Future
    subject = runtime()
    subject._schedule_recommendations = LiveMatchRuntime._schedule_recommendations.__get__(subject)

    class Pool:
        def __init__(self): self.requests = []
        def submit(self, callback, context):
            future = Future()
            self.requests.append((context, future))
            return future

    pool = Pool()
    subject._recommendation_pool = pool
    match = sample(120)
    subject._update(match)
    assert len(pool.requests) == 1
    context, future = pool.requests[0]
    assert context["players"][context["local_player_key"]]["current_gold"] == 450
    match["game_time"] = 122
    match["local_live_stats"]["currentGold"] = 850
    subject._update(match)
    assert len(pool.requests) == 1
    match["all_players"][1]["items"] = [{"itemID": 1036}]
    subject._update(match)
    future.set_result({"recommendations": [{"id": "stale"}], "skillOrder": {"status": "unavailable", "order": []}})
    assert subject._recommendations == []
    subject._update(match)
    assert len(pool.requests) == 2
    subject.stop_event.set()
    pool.requests[1][1].set_result({"recommendations": [{"id": "late"}], "skillOrder": {"status": "unavailable", "order": []}})
    assert subject._recommendations == []
    subject.tracker.finish(persist=False)


def test_real_preparation_worker_publishes_rank_skill_recipe_and_updates_gold_without_rescoring():
    from concurrent.futures import ThreadPoolExecutor
    subject = runtime()
    subject._preparation_service = None
    subject._schedule_recommendations = LiveMatchRuntime._schedule_recommendations.__get__(subject)
    subject._recommendation_pool = ThreadPoolExecutor(max_workers=1)
    match = sample(120)
    match["all_players"][0]["position"] = "MIDDLE"
    subject.game.get_live_snapshot = lambda: match
    try:
        subject._tick()
        first_future = subject._recommendation_future
        result = first_future.result(timeout=20)
        subject._recommendation_pool.shutdown(wait=True)
        published = subject.snapshot()["snapshot"]
        assert len(result["recommendations"]) >= 3
        assert len(published["recommendations"]) == 3
        assert published["skillOrder"]["status"] == "available"
        assert published["skillOrder"]["role"] == "mid"
        assert all(row["nextPurchase"] for row in published["recommendations"])
        assert [row["score"] for row in published["recommendations"]] == [row["score"] for row in result["recommendations"][:3]]
        match["game_time"] = 122
        match["local_live_stats"]["currentGold"] = 2200
        subject._tick()
        assert subject._recommendation_future is first_future
        assert any(row["nextPurchase"]["status"] == "buy" for row in subject.snapshot()["snapshot"]["recommendations"])
    finally:
        subject.stop_event.set()
        subject._recommendation_pool.shutdown(wait=True, cancel_futures=True)
        subject.sound_service.close()
        subject.tracker.finish(persist=False)


def test_live_inventory_updates_replace_overlay_card_and_restore_it_after_sale():
    from app.services.live_preparation_service import LivePreparationService

    subject = runtime()
    subject._preparation_service = LivePreparationService(subject.items)
    subject._recommendations = [
        {"id": ident, "name": subject.items[ident]["name"], "score": 90 - index}
        for index, ident in enumerate(("3100", "3157", "3089", "6655"))
    ]
    frame = sample(120)
    frame["local_live_stats"]["currentGold"] = 2000
    def shown():
        snap = subject.snapshot()["snapshot"]
        assert snap["overlay"]["recommendations"] == snap["recommendations"]
        return snap["recommendations"]

    subject._update(frame)
    first = shown()
    assert [row["id"] for row in first] == ["3100", "3157", "3089"]
    frame["all_players"][0]["items"] = [{"itemID": 1056}, {"itemID": 3057}]
    subject._update(frame)
    component = shown()
    assert [row["id"] for row in component] == [row["id"] for row in first]
    assert component[0]["nextPurchase"]["id"] != first[0]["nextPurchase"]["id"]
    frame["all_players"][0]["items"] = [{"itemID": 1056}, {"itemID": 3100}]
    subject._update(frame)
    assert [row["id"] for row in shown()] == ["3157", "3089", "6655"]
    frame["all_players"][0]["items"] = [{"itemID": 1056}]
    subject._update(frame)
    assert [row["id"] for row in shown()] == ["3100", "3157", "3089"]
    subject.tracker.finish(persist=False)


def test_installed_game_version_is_read_once_per_live_session():
    subject = runtime()
    calls = []
    class Response:
        status_code = 200
        def json(self): return "16.20.1"
    class Client:
        port = 12345
        class session:
            @staticmethod
            def get(url, timeout):
                calls.append((url, timeout))
                return Response()
    subject.lcu = Client()
    assert subject._current_game_version("match-1") == "16.20.1"
    assert subject._current_game_version("match-1") == "16.20.1"
    assert len(calls) == 1 and calls[0][1] == 1.2
    assert subject._current_game_version("match-2") == "16.20.1"
    assert len(calls) == 2


def test_runtime_keeps_turret_as_killer_actor_and_briar_as_victim():
    subject = runtime()
    match = sample(754.2)
    match["all_players"][1]["championName"] = "Briar"
    match["game_events"] = [{"EventID": 221, "EventName": "ChampionKill", "EventTime": 754.2,
                             "KillerName": "Turret_T2_L_03_A", "VictimName": "Enemy#EUW", "Assisters": []}]
    subject.game.get_live_snapshot = lambda: match
    subject._tick()

    event = subject.snapshot()["snapshot"]["events"][0]
    assert event["EventName"] == "ChampionKill"
    assert event["KillerActorType"] == "tower"
    assert event["KillerActorName"] == "torre"
    assert "KillerChampion" not in event
    assert event["VictimActorType"] == "champion"
    assert event["VictimChampion"] == "Briar"
    assert event["EventTime"] == 754.2
    assert event["EventDescription"] == "Briar murió por una torre"
    assert "KillerName" not in event and "VictimName" not in event
    subject.tracker.finish(persist=False)


def test_client_disconnect_retains_live_snapshot_during_reconnect_grace():
    subject = runtime()
    subject._tick()
    subject.lcu.is_connected = lambda: False
    subject._tick()
    state = subject.snapshot()
    assert state["telemetry"] == "stale"
    assert state["snapshot"] is not None
    subject.tracker.finish(persist=False)


def test_disconnected_client_state_and_reconnection_reuse_the_same_session():
    subject = runtime()
    subject.lcu.is_connected = lambda: False
    subject._tick()
    assert subject.snapshot()["state"] == "disconnected"
    subject.lcu.is_connected = lambda: True
    subject._gameflow_phase = lambda: "InProgress"
    subject._tick()
    first_id = subject.snapshot()["sessionId"]
    subject.lcu.is_connected = lambda: False
    subject._tick()
    subject.lcu.is_connected = lambda: True
    subject._tick()
    assert subject.snapshot()["telemetry"] == "current"
    assert subject.snapshot()["sessionId"] == first_id
    subject.tracker.finish(persist=False)


@pytest.mark.parametrize(("phase", "expected"), [
    ("None", "connected"), ("Lobby", "lobby"), ("Matchmaking", "lobby"),
    ("ChampSelect", "champion_select"), ("GameStart", "loading"),
    ("WaitingForStats", "post_game"), ("EndOfGame", "post_game"),
])
def test_gameflow_lifecycle_states(phase: str, expected: str):
    subject = runtime()
    subject._gameflow_phase = lambda: phase
    subject.game.get_live_snapshot = lambda: None
    subject._tick()
    assert subject.snapshot()["state"] == expected


@pytest.mark.parametrize("mode", ["CLASSIC", "PRACTICETOOL", "ARAM"])
def test_available_game_modes_use_actual_telemetry_without_special_case(mode: str):
    subject = runtime()
    match = sample()
    match["game_mode"] = mode
    subject.game.get_live_snapshot = lambda: match
    subject._tick()
    assert subject.snapshot()["snapshot"]["gameMode"] == mode
    subject.tracker.finish(persist=False)


def test_player_death_and_item_change_are_observed_incrementally():
    subject = runtime()
    subject._tick()
    changed = sample(22)
    changed["all_players"][0]["scores"]["deaths"] = 1
    changed["all_players"][0]["items"] = [{"itemID": 1056}, {"itemID": 2003}]
    changed["local_player"] = changed["all_players"][0]
    subject.game.get_live_snapshot = lambda: changed
    subject._tick()
    state = subject.snapshot()["snapshot"]
    assert state["localPlayer"]["scores"]["deaths"] == 1
    assert [item["itemID"] for item in state["localPlayer"]["items"]] == [1056, 2003]
    subject.tracker.finish(persist=False)


def test_temporary_telemetry_failure_does_not_end_session():
    subject = runtime()
    subject._tick()
    subject.game.get_live_snapshot = lambda: None
    subject._tick()
    state = subject.snapshot()
    assert state["state"] == "active"
    assert state["telemetry"] == "stale"
    assert state["snapshot"] is not None
    subject.tracker.finish(persist=False)


def test_completed_session_queues_existing_deferred_reconciliation():
    subject = runtime()
    subject._tick()
    queued = []
    subject.on_completed = lambda: queued.append(True)
    subject._finish()
    assert queued == [True]
    assert subject.snapshot().get("completedSessionId")


def test_postgame_preserves_snapshot_scoreboard_and_event_history():
    subject = runtime()
    subject._tick()
    previous = subject.snapshot()["snapshot"]
    subject._gameflow_phase = lambda: "EndOfGame"
    subject._tick()
    state = subject.snapshot()
    assert state["state"] == "post_game"
    assert state["snapshot"] == previous
    assert state["postGame"]["localChampion"] == "Ahri"
    assert len(state["postGame"]["players"]) == 2
    assert {event["EventName"] for event in state["postGame"]["events"]} >= {"ChampionKill", "DragonKill"}


def test_explicit_first_blood_achievement_survives_postgame_finalization():
    subject = runtime()
    match = sample()
    match["game_events"][0]["IsFirstBlood"] = True
    subject.game.get_live_snapshot = lambda: match
    subject._tick()
    subject._finish()
    events = subject.snapshot()["postGame"]["events"]
    kill = next(event for event in events if event["EventName"] == "ChampionKill")
    first_blood = next(event for event in events if event["EventName"] == "FirstBlood")
    assert kill["KillerChampion"] == "Ahri"
    assert first_blood["KillerChampion"] == "Ahri"
    assert first_blood["EventTeam"] == "ORDER"


def test_postgame_state_is_cleared_when_a_new_live_session_begins():
    subject = runtime()
    subject._tick()
    subject._finish()
    old_session = subject.snapshot()["postGame"]["sessionId"]
    subject.game.get_live_snapshot = lambda: sample(10)
    subject._tick()
    state = subject.snapshot()
    assert state["state"] == "active"
    assert state["sessionId"] != old_session
    assert state.get("postGame") is None


def test_generic_active_player_event_alias_resolves_only_to_identified_local_player():
    subject = runtime()
    match = sample()
    match["game_events"] = [{"EventID": 99, "EventTime": 20, "EventName": "ChampionKill",
                             "KillerName": "Jugador", "VictimName": "Enemy#EUW"}]
    subject.game.get_live_snapshot = lambda: match
    subject._tick()
    event = subject.snapshot()["snapshot"]["events"][0]
    assert event["KillerChampion"] == "Ahri"
    assert event["KillerLocal"] is True
    subject.tracker.finish(persist=False)


def test_completed_item_observation_uses_baseline_and_rebases_after_api_gap():
    tracker = LiveMatchTracker(_item_catalog(), persist=False)
    first = sample(20)
    tracker.start(first)
    assert not any(event["type"] == "completed_item_acquired" for event in tracker.session["events"])
    changed = sample(22)
    changed["all_players"][0]["items"].append({"itemID": 3100, "displayName": "Perdición del liche"})
    tracker.update(changed)
    complete_events = [event for event in tracker.session["events"] if event["type"] == "completed_item_acquired"]
    assert len(complete_events) == 1
    assert complete_events[0]["item_id"] == 3100
    assert complete_events[0]["precision"] == "observed"
    tracker.mark_telemetry_gap()
    after_gap = sample(24)
    after_gap["all_players"][0]["items"].append({"itemID": 3089, "displayName": "Sombrero mortal de Rabadon"})
    tracker.update(after_gap)
    assert len([event for event in tracker.session["events"] if event["type"] == "completed_item_acquired"]) == 1
    tracker.finish(persist=False)


def test_rune_asset_catalog_resolves_stable_ids_and_display_names(monkeypatch):
    from backend import assets

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"id": 8000, "name": "Precision", "icon": "perk-images/Styles/Precision/Precision.png",
                     "slots": [{"runes": [{"id": 8005, "name": "Press the Attack",
                                               "icon": "perk-images/Styles/Precision/PressTheAttack/PressTheAttack.png"}]}]}]

    monkeypatch.setattr(assets.requests, "get", lambda *args, **kwargs: Response())
    mapping = assets._rune_icons_by_id("18.99.1")
    assert mapping["8005"].endswith("PressTheAttack.png")
    assert mapping["presstheattack"] == mapping["8005"]
    assert mapping["precision"].endswith("Precision.png")
    assert assets._STAT_SHARDS["5001"] == "statmodshealthscalingicon.png"


def test_scaling_health_shard_uses_stat_shard_asset_resolver(monkeypatch, tmp_path):
    from backend import assets

    icon = tmp_path / "scaling-health.png"
    icon.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    requested = []
    monkeypatch.setattr(assets, "_cached_or_download", lambda url, path: requested.append(url) or icon)
    result = assets._resolve_rune_image("5001", {}, "16.20.1", tmp_path)
    assert result and result.startswith("data:image/png;base64,")
    assert requested and requested[0].endswith("statmodshealthscalingicon.png")


@pytest.mark.parametrize(("player_kills", "assists", "other_kills", "expected"), [
    (10, 0, 13, 10 / 23 * 100),
    (3, 7, 17, 50.0),
])
def test_kill_participation_uses_allied_team_kills(player_kills, assists, other_kills, expected):
    players = [
        {"championName": "Gragas", "team": "ORDER", "riotId": "Local#EUW",
         "scores": {"kills": player_kills, "assists": assists}},
        {"championName": "Lux", "team": "ORDER", "scores": {"kills": other_kills, "assists": 0}},
        {"championName": "Enemy", "team": "CHAOS", "scores": {"kills": 40, "assists": 0}},
    ]
    value = calculate_kill_participation(players, "ORDER", players[0])
    assert value == pytest.approx(expected)


def test_kill_participation_handles_zero_and_inconsistent_snapshots():
    players = [{"team": "ORDER", "riotId": "Local#EUW", "scores": {"kills": 0, "assists": 0}},
               {"team": "ORDER", "scores": {"kills": 0, "assists": 0}}]
    assert calculate_kill_participation(players, "ORDER", players[0]) == 0
    players[0]["scores"] = {"kills": 10, "assists": 3}
    assert calculate_kill_participation(players, "ORDER", players[0]) is None


@pytest.mark.parametrize(("raw", "kind", "label"), [
    ({"KillerName": "Minion_T200L2S01N0003"}, "minion", "súbditos"),
    ({"KillerName": "Turret_T2_L_03_A"}, "tower", "una torre"),
    ({"KillerName": "SRU_Blue"}, "neutral_monster", "un monstruo neutral"),
])
def test_live_event_normalizer_classifies_non_champion_actors(raw, kind, label):
    event = normalize_live_event({"EventName": "ChampionKill", "VictimName": "Gragas", **raw}, victim_champion="Gragas")
    assert event["KillerActorType"] == kind
    assert event["VictimActorType"] == "champion"
    assert event["EventDescription"] == f"Gragas murió por {label}"


def test_live_event_normalizer_localizes_objective_variants():
    horde = normalize_live_event({"EventID": 10, "EventName": "HordeKill", "KillerName": "Gragas"}, "Gragas")
    baron = normalize_live_event({"EventName": "BaronKill", "KillerName": "Gragas"}, "Gragas")
    respawn = normalize_live_event({"EventName": "InhibRespawned", "InhibRespawned": "Barracks_T1_L1"})
    assert (horde["ObjectiveKind"], horde["ObjectiveLabel"]) == ("void_grub", "Larva del Vacío eliminada")
    assert baron["ObjectiveLabel"] == "Barón Nashor eliminado"
    assert respawn["ObjectiveKind"] == "inhibitor_respawned"


def test_tracker_keeps_distinct_horde_ids_and_non_champion_structure_actor():
    match = sample()
    match["game_events"] = [
        {"EventID": 101, "EventTime": 300, "EventName": "HordeKill", "KillerName": "Player#EUW"},
        {"EventID": 102, "EventTime": 302, "EventName": "HordeKill", "KillerName": "Player#EUW"},
        {"EventID": 103, "EventTime": 304, "EventName": "TurretKilled", "KillerName": "Minion_T200L2S01N0003",
         "TurretKilled": "Turret_T1_L2_A"},
    ]
    tracker = LiveMatchTracker({}, persist=False)
    tracker.start(match)
    objectives = [event for event in tracker.session["events"] if event["type"] == "objective"]
    grubs = [event for event in objectives if event.get("objective") == "void_grub"]
    tower = next(event for event in objectives if event.get("objective") == "tower")
    assert [event["event_id"] for event in grubs] == ["native:101", "native:102"]
    assert tower["killer_actor_type"] == "minion"
    assert tower["target_actor_type"] == "tower"
    tracker.finish(persist=False)


def test_turret_champion_death_keeps_tower_source_and_validates_event_time():
    raw = {"EventName": "ChampionKill", "EventTime": 125.75,
           "KillerName": "Turret_T2_L_03_A", "VictimName": "Briar#EUW"}
    event = normalize_live_event(raw, killer_champion="Ahri", victim_champion="Briar")
    assert event["KillerActorType"] == "tower"
    assert event["KillerActorName"] == "torre"
    assert "KillerChampion" not in event
    assert event["VictimActorType"] == "champion"
    assert event["EventDescription"] == "Briar murió por una torre"
    assert event["EventTime"] == 125.75
    assert normalize_live_event({**raw, "EventTime": -2}, victim_champion="Briar")["EventTime"] is None
    assert normalize_live_event({**raw, "EventTime": None}, victim_champion="Briar")["EventTime"] is None
    destroyed = normalize_live_event({"EventName": "TurretKilled", "EventTime": 130,
                                      "TurretKilled": "Turret_T2_L_03_A"})
    assert destroyed["ObjectiveKind"] == "tower"
    assert destroyed["EventDescription"] == "Torre destruida"
    unknown = normalize_live_event({"EventName": "ChampionKill", "EventTime": 131,
                                    "VictimName": "Briar#EUW"}, victim_champion="Briar")
    assert unknown["KillerActorType"] == "unknown"
    assert "KillerChampion" not in unknown
    assert unknown["EventDescription"] == "Briar murió por una causa no identificada"


def test_completed_item_classifier_uses_patch_catalog_and_excludes_inventory_noise():
    subject = LiveMatchTracker(_item_catalog(), persist=False)
    for item_id in (1056, 2003, 1036, 1001, 3340, 2055):
        assert subject._is_completed_item(item_id) is False
    for item_id in (3006, 3100, 3157, 3870):
        assert subject._is_completed_item(item_id) is True
    item_name = subject._item_name(3100)
    assert "\\u" not in item_name
    assert "Perdición" in item_name


@pytest.mark.parametrize("item_id", [1055, 2003, 1036, 1001])
def test_runtime_keeps_minor_inventory_changes_internal_without_timeline_events(item_id):
    subject = runtime()
    subject._tick()
    changed = sample(22)
    changed["all_players"][0]["items"].append({"itemID": item_id})
    changed["local_player"] = changed["all_players"][0]
    subject.game.get_live_snapshot = lambda: changed
    subject._tick()

    session_events = subject.tracker.session["events"]
    assert any(event["type"] == "item_purchase" and event["item_id"] == item_id for event in session_events)
    visible = subject.snapshot()["snapshot"]["events"]
    assert not any(event["EventName"] in {"CompletedItemAcquired", "InventoryItemObserved"}
                   and event["ItemId"] == item_id for event in visible)
    subject._finish()


def test_runtime_emits_inventory_observations_and_sanitized_actor_categories():
    subject = runtime()
    subject._tick()
    changed = sample(22)
    changed["all_players"][0]["items"].append({"itemID": 3100, "displayName": "Perdición del liche"})
    changed["local_player"] = changed["all_players"][0]
    changed["game_events"] = [{"EventID": 110, "EventTime": 22, "EventName": "ChampionKill",
                               "KillerName": "Minion_T200L2S01N0003", "VictimName": "Enemy#EUW"}]
    subject.game.get_live_snapshot = lambda: changed
    subject._tick()
    events = subject.snapshot()["snapshot"]["events"]
    kill = next(event for event in events if event["EventName"] == "ChampionKill")
    observed = next(event for event in events if event["EventName"] == "CompletedItemAcquired")
    subject.game.get_live_snapshot = lambda: changed
    subject._tick()
    events = subject.snapshot()["snapshot"]["events"]
    assert len([event for event in events if event["EventName"] == "CompletedItemAcquired"]) == 1
    assert kill["KillerActorType"] == "minion"
    assert kill["EventDescription"] == "Garen murió por súbditos"
    assert "KillerName" not in kill and "VictimName" not in kill
    assert observed["ObservedOnly"] is True
    assert observed["ItemId"] == 3100
    assert "Hora aproximada" not in str(observed)
    subject._finish()
    archived = next(event for event in subject.snapshot()["postGame"]["events"] if event["EventID"] == "native:110")
    assert archived["KillerActorType"] == "minion"
    assert archived["EventDescription"] == "Garen murió por súbditos"


def test_game_ending_keeps_session_until_postgame_and_finishes_once():
    subject = runtime()
    subject._tick()
    session_id = subject.snapshot()["sessionId"]
    subject._gameflow_phase = lambda: "PreEndOfGame"
    subject._tick()
    assert subject.snapshot()["state"] == "game_ending"
    assert subject.snapshot()["sessionId"] == session_id
    subject._gameflow_phase = lambda: "EndOfGame"
    subject._tick()
    assert subject.snapshot()["state"] == "post_game"
    assert subject.snapshot()["completedSessionId"] == session_id
    assert subject.tracker.is_tracking is False


def test_live_session_id_is_sent_to_existing_recording_runtime():
    subject = runtime()
    associated = []
    subject.recordings = type("Recorder", (), {"associate_live_session": lambda self, value, metadata=None: associated.append(value)})()
    subject._tick()
    assert associated == [subject.snapshot()["sessionId"]]
    assert associated[0]
    subject.tracker.finish(persist=False)
