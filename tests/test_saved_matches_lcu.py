from backend.saved_matches import persist_latest_local_lcu_match, _local_summary
from backend.soloq_analyses import _normalize_events, _public_participant
from backend.match_deletion import _resolve_scope
from app.services.home_history_service import HomeHistoryRepository
from app.services.live_match_tracker import LiveMatchTracker
import json

def seed_profile(repository, profile):
    path = repository.root / repository.account_key(profile)
    path.mkdir(parents=True, exist_ok=True)
    (path / "profile.json").write_text(json.dumps(profile), encoding="utf-8")


def test_local_lcu_snapshot_is_lightweight_and_preserves_riot_layer(tmp_path):
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "account-1"}
    seed_profile(repository, profile)
    repository.merge(profile, [
        {"stable_match_id": "EUW1_123", "data_quality": {"source": "LCU"},
         "champion_id": 233, "champion_name": "Briar", "queue_id": 420,
         "started_at": "2026-10-20T10:00:00Z", "duration_seconds": 1800,
         "result": "victory", "kills": 5, "deaths": 3, "assists": 4,
         "participants": [{"participant_id": 1, "champion_id": 233, "champion_name": "Briar", "is_local": True}]},
    ])
    repository.save_soloq_analysis(profile, {"match_id": "EUW1_OLD", "status": "ready"})
    record = persist_latest_local_lcu_match(repository, profile)
    assert record["match_id"] == "EUW1_123"
    assert record["source"] == "LCU" and not record["deep_analysis"]
    assert "participants" in record and "frames" not in record
    assert repository.load_saved_analyses(profile)[0]["match_id"] == "EUW1_OLD"
    assert _local_summary(record)["analysisState"] == "pending"


def test_local_lcu_limit_does_not_evict_existing_records(tmp_path):
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "account-2"}
    seed_profile(repository, profile)
    for index in range(2):
        assert repository.save_lcu_match(profile, {"match_id": str(index), "source": "LCU"}, limit=2)
    assert not repository.save_lcu_match(profile, {"match_id": "third", "source": "LCU"}, limit=2)
    assert [item["match_id"] for item in repository.load_saved_lcu_matches(profile)] == ["0", "1"]


def test_useful_damage_accumulates_without_decreasing():
    participants = [
        {"participantId": 1, "champion": "Jax", "teamId": 100, "side": "allied"},
        {"participantId": 2, "champion": "Briar", "teamId": 100, "side": "allied"},
        {"participantId": 3, "champion": "Illaoi", "teamId": 200, "side": "enemy"},
        {"participantId": 4, "champion": "Diana", "teamId": 200, "side": "enemy"},
    ]
    events = [
        {"type": "CHAMPION_KILL", "timestamp": 1000, "killerId": 2, "victimId": 3, "killerTeamId": 100, "victimDamageReceived": []},
        {"type": "CHAMPION_KILL", "timestamp": 2000, "killerId": 1, "victimId": 4, "killerTeamId": 100, "victimDamageReceived": []},
        {"type": "CHAMPION_KILL", "timestamp": 3000, "killerId": 3, "victimId": 2, "killerTeamId": 200,
         "victimDamageReceived": [{"participantId": 3, "damage": 1000}]},
        {"type": "CHAMPION_KILL", "timestamp": 4000, "killerId": 4, "victimId": 2, "killerTeamId": 200,
         "victimDamageReceived": [{"participantId": 4, "damage": 2000}]},
    ]
    timeline = {"info": {"frames": [{"timestamp": 0, "events": events}]}}
    normalized, _ = _normalize_events(timeline, participants)
    victim_events = [item for item in normalized if item["victimId"] == 2]
    values = [item["usefulDamageReceived"] for item in victim_events]
    assert values == [500.0, 1500.0]
    assert all(current >= previous for previous, current in zip(values, values[1:]))
    assert victim_events[-1]["championDamageReceivedCumulative"] == 3000.0
    assert victim_events[-1]["championDamageReceivedDelta"] == 2000.0


def test_damage_normalization_filters_sources_and_uses_champion_timeline_fields():
    participants = [
        {"participantId": 1, "champion": "A", "teamId": 100, "side": "allied"},
        {"participantId": 2, "champion": "B", "teamId": 100, "side": "allied"},
        {"participantId": 3, "champion": "C", "teamId": 200, "side": "enemy"},
    ]
    timeline = {"info": {"frames": [{"timestamp": 0,
        "participantFrames": {"1": {"damageStats": {
            "totalDamageDone": 99999, "totalDamageTaken": 88888,
            "physicalDamageDoneToChampions": 100, "magicDamageDoneToChampions": 200,
            "trueDamageDoneToChampions": 300}},
            "2": {"damageStats": {"totalDamageDoneToChampions": 450}}},
        "events": [{"type": "CHAMPION_KILL", "timestamp": 500, "killerId": 2,
            "killerTeamId": 100, "victimId": 3, "assistingParticipantIds": [1]},
            {"type": "CHAMPION_KILL", "timestamp": 1000, "killerId": 3,
            "killerTeamId": 200, "victimId": 1, "victimDamageReceived": [
                {"participantId": 2, "damage": 1000},  # ally: not champion combat damage received
                {"participantId": 3, "physicalDamage": 400, "magicDamage": 500, "trueDamage": 100},
                {"participantId": 99, "damage": 777},  # non-roster/environmental source
            ]}]}]}}
    events, frames = _normalize_events(timeline, participants)
    assert [frame["championDamageDealt"] for frame in frames] == [600, 450]
    assert [frame["allSourceDamageReceived"] for frame in frames] == [88888, None]
    event = events[1]
    assert event["championDamageReceivedDelta"] == 1000
    assert event["allSourceDamageReceivedDelta"] == 2777
    assert event["usefulDamageReceived"] == 1000


def test_match_v5_final_damage_scope_is_explicit():
    participant = _public_participant({
        "participant_id": 1, "team_id": 100,
        "total_damage_dealt_to_champions": 12_345,
        "total_damage_taken": 67_890,
        "damage_to_objectives": 9000, "damage_to_epic_monsters": 5000,
        "damage_dealt_to_buildings": 4000, "damage_dealt_to_turrets": 3900,
    }, "puuid")
    assert participant["championDamageDealt"] == 12_345
    assert participant["championDamageReceived"] is None
    assert participant["championDamageReceivedCoverage"] == "unavailable"
    assert participant["allSourceDamageReceived"] == 67_890
    assert participant["damageToObjectives"] == 9000
    assert participant["damageToEpicMonsters"] == 5000
    assert participant["damageToBuildings"] == 4000
    assert "damageTaken" not in participant


def test_deletion_scope_resolves_lcu_entry_by_stable_match_id(tmp_path):
    repository = HomeHistoryRepository(tmp_path)
    profile = {"puuid": "account-delete-scope"}
    seed_profile(repository, profile)
    repository.save_lcu_match(profile, {"match_id": "EUW1_SCOPE_TEST", "source": "LCU", "champion": "Briar"})
    scope = _resolve_scope(session_id=None, match_id="EUW1_SCOPE_TEST", repository=repository)
    assert scope["local_record"]["champion"] == "Briar"
    assert "EUW1_SCOPE_TEST" in scope["riot_ids"]


def test_saved_matches_lists_full_cached_lcu_history_without_ten_entry_cap(tmp_path, monkeypatch):
    profile = {"puuid": "history-browser-player", "region": "EUW1"}
    repository = HomeHistoryRepository(tmp_path)
    seed_profile(repository, profile)
    repository.merge(profile, [
        {"stable_match_id": f"EUW1_{index}", "game_id": f"EUW1_{index}",
         "data_quality": {"source": "LCU"}, "queue_id": 420, "mode": "CLASSIC",
         "champion_id": 233, "champion_name": "Briar", "started_at": f"2026-10-{20-index:02d}T10:00:00Z",
         "duration_seconds": 1800, "result": "victory", "kills": 5, "deaths": 3, "assists": 4,
         "participants": [{"participant_id": 1, "team_id": 100, "champion_id": 233,
                           "champion_name": "Briar", "is_local": True, "kills": 5},
                          {"participant_id": 6, "team_id": 200, "champion_id": 22,
                           "champion_name": "Ashe", "is_local": False, "kills": 2}],}
        for index in range(12)
    ])
    monkeypatch.setattr(repository, "load_last_profile", lambda: profile)
    monkeypatch.setattr("app.services.home_history_service.HomeHistoryRepository", lambda: repository)
    monkeypatch.setattr("backend.saved_matches._tracker", lambda: LiveMatchTracker({}, persist=False))

    result = __import__("backend.saved_matches", fromlist=["list_saved_matches"]).list_saved_matches()

    assert result["historyCount"] == 12
    assert len(result["matches"]) == 12
    assert result["analysisCount"] == 0
    assert result["limit"] == 10
    assert result["matches"][0]["queueId"] == 420
    detail = __import__("backend.saved_matches", fromlist=["get_saved_match"]).get_saved_match("EUW1_0")
    assert detail["participants"][0]["side"] == "allied"
    assert detail["participants"][1]["side"] == "enemy"


def test_registering_history_match_does_not_create_lcu_snapshot(tmp_path, monkeypatch):
    from backend.soloq_analyses import register_analysis

    profile = {"puuid": "history-browser-player", "region": "EUW1", "ranked": []}
    repository = HomeHistoryRepository(tmp_path)
    seed_profile(repository, profile)
    repository.merge(profile, [{"stable_match_id": "EUW1_900", "game_id": "EUW1_900",
        "data_quality": {"source": "LCU"}, "queue_id": 420, "mode": "CLASSIC",
        "champion_id": 233, "champion_name": "Briar", "started_at": "2026-10-20T10:00:00Z",
        "duration_seconds": 1800, "result": "victory", "kills": 5, "deaths": 3, "assists": 4}])
    repository.merge(profile, [{"stable_match_id": "EUW1_901", "game_id": "EUW1_901",
        "data_quality": {"source": "LCU"}, "queue_id": 420, "mode": "CLASSIC",
        "champion_id": 233, "champion_name": "Briar", "started_at": "2026-10-19T10:00:00Z",
        "duration_seconds": 1800, "result": "victory", "kills": 5, "deaths": 3, "assists": 4}])
    monkeypatch.setattr(HomeHistoryRepository, "load_last_profile", lambda self: profile)
    monkeypatch.setattr("backend.soloq_analyses._legacy_saved_count", lambda: 0)
    result = register_analysis(repository, "EUW1_900")
    assert result["match_id"] == "EUW1_900"
    assert repository.load_saved_lcu_matches(profile) == []

    for index in range(9):
        repository.save_soloq_analysis(profile, {"match_id": f"EUW1_OLD{index}", "status": "ready"})
    # Ten retained analyses prevent an eleventh, while the LCU history is still separate.
    import pytest
    with pytest.raises(ValueError, match="límite de 10 análisis"):
        register_analysis(repository, "EUW1_901")
    assert repository.load_saved_lcu_matches(profile) == []
