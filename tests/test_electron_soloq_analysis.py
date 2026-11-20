from __future__ import annotations

from pathlib import Path

import pytest

from app.services.home_history_service import HomeHistoryRepository
from app.services.riot_api_service import RiotApiService
from backend import soloq_analyses as soloq


@pytest.fixture(autouse=True)
def _empty_legacy_collection(monkeypatch):
    monkeypatch.setattr(soloq, "_legacy_saved_count", lambda: 0)


def _repo(tmp_path: Path, count: int = 1) -> tuple[HomeHistoryRepository, dict]:
    repository = HomeHistoryRepository(tmp_path / "profiles")
    profile = {"puuid": "local-puuid", "gameName": "Local", "tagLine": "EUW", "region": "EUW1"}
    matches = [{
        "stable_match_id": f"EUW1_{1000 + index}", "game_id": f"EUW1_{1000 + index}",
        "queue_id": 420, "started_at": "2026-10-20T10:00:00+00:00", "duration_seconds": 1800,
        "mode": "CLASSIC", "champion_id": "Briar", "champion_name": "Briar",
        "lane": "JUNGLE", "kills": 5, "deaths": 3, "assists": 4, "result": "victory",
    } for index in range(count)]
    repository.merge(profile, matches)
    return repository, profile


def test_register_is_match_id_keyed_deduplicated_and_queue_420_only(tmp_path: Path):
    repository, _ = _repo(tmp_path)
    saved = soloq.register_analysis(repository, "EUW1_1000")
    duplicate = soloq.register_analysis(repository, "EUW1_1000")
    assert saved["match_id"] == "EUW1_1000"
    assert duplicate["match_id"] == saved["match_id"]
    assert len(soloq.list_analyses(repository)["matches"]) == 1

    profile = repository.load_last_profile()
    repository.merge(profile, [{"stable_match_id": "EUW1_aram", "game_id": "EUW1_aram", "queue_id": 450}])
    with pytest.raises(ValueError, match="cola 420"):
        soloq.register_analysis(repository, "EUW1_aram")


def test_register_does_not_requeue_saved_partial_analysis_with_timeline(tmp_path: Path):
    repository, profile = _repo(tmp_path)
    record = soloq.register_analysis(repository, "EUW1_1000")
    record.update({
        "status": "partial", "status_message": "Identidad local sin confirmar.",
        "timeline_available": True, "local_identity_resolved": False,
        "participants": [{"participantId": 1, "champion": "Briar"}],
        "events": [], "frames": [{"timestamp": 0, "participants": []}],
    })
    repository.save_soloq_analysis(profile, record)

    registered = soloq.register_analysis(repository, "EUW1_1000")

    assert registered["status"] == "partial"
    assert registered["status_message"] == "Identidad local sin confirmar."
    assert registered["timeline_available"] is True


def test_deep_analysis_is_not_ready_until_download_and_identity_are_complete():
    complete = {
        "status": "ready", "timeline_available": True, "local_identity_resolved": True,
        "participants": [{"participantId": 1}], "frames": [{"timestamp": 0}],
    }
    assert soloq.is_deep_analysis_ready(complete)
    for incomplete in (
        {**complete, "status": "processing"},
        {**complete, "timeline_available": False},
        {**complete, "local_identity_resolved": False},
        {**complete, "frames": []},
        {**complete, "participants": []},
    ):
        assert not soloq.is_deep_analysis_ready(incomplete)


def test_download_reuses_persisted_timeline_without_touching_riot(monkeypatch, tmp_path: Path):
    repository, profile = _repo(tmp_path)
    record = soloq.register_analysis(repository, "EUW1_1000")
    record.update({
        # A previous version could leave a durable analysis in `pending`
        # after re-registering a partial-coverage match.
        "status": "pending", "timeline_available": True,
        "participants": [{"participantId": 1, "champion": "Briar", "local": False}],
        "events": [{"id": "event-1", "type": "CHAMPION_KILL", "timestamp": 1}],
        "frames": [{"timestamp": 0, "participants": []}],
    })
    repository.save_soloq_analysis(profile, record)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("No se debe consultar Riot para una cronología ya guardada")

    monkeypatch.setattr(soloq.SettingsService, "load", unexpected)
    monkeypatch.setattr(soloq, "RiotApiService", unexpected)

    reused = soloq.download_match(repository, "EUW1_1000")

    assert reused["status"] == "partial"
    assert reused["events"] == record["events"]
    assert reused["frames"] == record["frames"]
    assert repository.load_saved_analyses(profile)[0]["participants"] == record["participants"]


def test_participant_detail_exposes_medal_metrics_and_keeps_missing_values_unknown():
    item = RiotApiService._participant_detail({
        "participantId": 1, "championId": 233, "teamId": 100, "puuid": "local-puuid",
        "totalHeal": 0, "timeCCingOthers": 37, "challenges": {"objectivesStolen": 1},
    }, is_player=True)
    assert item["total_heal"] == 0
    assert item["time_ccing_others"] == 37
    assert item["objectives_stolen"] == 1
    missing = RiotApiService._participant_detail({"participantId": 2}, is_player=False)
    assert missing["total_heal"] is None
    assert missing["time_ccing_others"] is None
    assert missing["objectives_stolen"] is None
    assert soloq._item_name(3006)


def test_detail_resolves_item_names_for_previously_cached_events(monkeypatch, tmp_path: Path):
    class EmptyCache:
        def get_timeline(self, _match_id): return None
    monkeypatch.setattr(soloq, "MatchHistoryCache", EmptyCache)
    repository, profile = _repo(tmp_path)
    repository.save_soloq_analysis(profile, {
        "match_id": "EUW1_1000", "status": "ready",
        "events": [{"id": "0:1:2", "type": "ITEM_PURCHASED", "itemId": 3006}],
    })
    detail = soloq.get_analysis(repository, "EUW1_1000")
    assert detail["events"][0]["itemName"] == soloq._item_name(3006)


def test_achievement_refresh_uses_saved_telemetry_without_rebuilding_battlescore(monkeypatch, tmp_path: Path):
    repository, profile = _repo(tmp_path)
    record = soloq.register_analysis(repository, "EUW1_1000")
    original_score = {"version": "battlescore_v2_3", "state": "partial", "participants": []}
    record.update({
        "battle_score": original_score,
        "duration": 1800,
        "timeline_available": True,
        "participants": [{"participantId": 1, "local": True, "side": "allied", "role": "JUNGLE",
            "kills": 0, "deaths": 12, "assists": 1, "cs": 100, "gold": 7000,
            "wardsPlaced": 0, "wardsKilled": 0, "detectorWardsPlaced": 0,
            "achievementAvailability": {"deaths": True, "kills": True, "assists": True}}],
        "events": [], "frames": [],
    })
    repository.save_soloq_analysis(profile, record)
    monkeypatch.setattr(soloq, "_attach_battlescore", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("No reconstruir BattleScore")))

    snapshot = soloq.get_achievement_snapshot(repository, "EUW1_1000")

    assert "achievements" in snapshot and "improvement_opportunities" in snapshot
    assert snapshot["improvement_opportunities"]["items"]
    assert repository.load_saved_analyses(profile)[0]["battle_score"] == original_score


def test_detail_rebuilds_older_timeline_with_small_purchases(monkeypatch, tmp_path: Path):
    timeline = {"info": {"frames": [{"timestamp": 1000, "events": [
        {"type": "ITEM_PURCHASED", "timestamp": 1000, "participantId": 1, "itemId": 1001},
    ]}]}}
    class CachedTimeline:
        def get_timeline(self, _match_id): return timeline
    monkeypatch.setattr(soloq, "MatchHistoryCache", CachedTimeline)
    repository, profile = _repo(tmp_path)
    repository.save_soloq_analysis(profile, {
        "match_id": "EUW1_1000", "status": "ready", "participants": [
            {"participantId": 1, "teamId": 100, "champion": "Briar", "side": "allied", "local": True},
        ], "events": [], "frames": [],
    })

    detail = soloq.get_analysis(repository, "EUW1_1000")
    assert [(event["type"], event["itemId"]) for event in detail["events"]] == [("ITEM_PURCHASED", 1001)]


def test_detail_rebuilds_and_persists_event_index_independently_of_ai(monkeypatch, tmp_path: Path):
    raw_events = [
        {"type": "CHAMPION_KILL", "timestamp": 600000, "killerId": 1, "victimId": 6,
         "assistingParticipantIds": [], "killerTeamId": 100},
        {"type": "CHAMPION_KILL", "timestamp": 612000, "killerId": 2, "victimId": 7,
         "assistingParticipantIds": [], "killerTeamId": 100},
        {"type": "CHAMPION_KILL", "timestamp": 627000, "killerId": 3, "victimId": 8,
         "assistingParticipantIds": [], "killerTeamId": 100},
        {"type": "CHAMPION_KILL", "timestamp": 638000, "killerId": 4, "victimId": 9,
         "assistingParticipantIds": [], "killerTeamId": 100},
        {"type": "ELITE_MONSTER_KILL", "timestamp": 650000, "killerId": 1,
         "killerTeamId": 100, "monsterType": "DRAGON"},
    ]
    timeline = {"info": {"frames": [{"timestamp": 600000, "events": raw_events}]}}

    class CachedTimeline:
        def get_timeline(self, _match_id): return timeline
        @staticmethod
        def get_raw_match(_match_id): return None

    monkeypatch.setattr(soloq, "MatchHistoryCache", CachedTimeline)
    monkeypatch.setattr(soloq, "_role_phase_references", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(soloq, "_attach_battlescore", lambda *_args, **_kwargs: {"state": "partial"})
    from app.services.match_analysis_evidence_service import MatchAnalysisEvidenceService
    build_evidence = MatchAnalysisEvidenceService.build_evidence
    build_calls = []
    def counted_build_evidence(self, source):
        build_calls.append(1)
        return build_evidence(self, source)
    monkeypatch.setattr(MatchAnalysisEvidenceService, "build_evidence", counted_build_evidence)
    repository, profile = _repo(tmp_path)
    participants = [{
        "participantId": index + 1, "champion": f"Champion{index}",
        "teamId": 100 if index < 5 else 200,
        "side": "allied" if index < 5 else "enemy", "local": index == 0,
        "role": "JUNGLE", "kills": 0, "deaths": 0, "assists": 0,
    } for index in range(10)]
    repository.save_soloq_analysis(profile, {
        "match_id": "EUW1_1000", "status": "ready", "duration": 1800, "win": True,
        "participants": participants, "events": [], "frames": [], "timeline_available": False,
        "ai_analysis": {"analysis": {
            "schema_version": 3, "analysis_type": "general_match_analysis",
            "summary": {"short_summary": "Las fases y el resumen deben conservarse."},
            "game_phases": {"early": {"assessment": "Inicio con escaramuzas."}},
        }},
    })

    detail = soloq.get_analysis(repository, "EUW1_1000")
    second_detail = soloq.get_analysis(repository, "EUW1_1000")
    saved = repository.load_saved_analyses(profile)[0]
    index = detail["timeline_event_index"]

    assert index["status"] == "available"
    assert index["timeline_extraction"]["source_events"] == 5
    assert len(index["teamfights"]) == 1
    assert len(index["objectives"]) == 1
    assert index["key_events"]
    assert second_detail["timeline_event_index"] == index
    assert len(build_calls) == 1
    assert detail["ai_analysis"]["analysis"]["game_phases"]["early"]["assessment"] == "Inicio con escaramuzas."
    assert detail["ai_analysis"]["analysis"]["match_evidence"]["evidence_version"] == 6
    assert saved["timeline_event_index"]["key_events"] == index["key_events"]


def test_detail_marks_unavailable_timeline_without_claiming_no_events(monkeypatch, tmp_path: Path):
    class EmptyCache:
        def get_timeline(self, _match_id): return None
    monkeypatch.setattr(soloq, "MatchHistoryCache", EmptyCache)
    repository, profile = _repo(tmp_path)
    repository.save_soloq_analysis(profile, {
        "match_id": "EUW1_1000", "status": "ready", "timeline_available": False,
        "participants": [], "events": [], "frames": [],
    })

    detail = soloq.get_analysis(repository, "EUW1_1000")

    assert detail["timeline_event_index"]["status"] == "missing_local"
    assert detail["timeline_event_index"]["notable_timeline"] == []


def test_saved_analysis_limit_does_not_trim_existing_records(tmp_path: Path):
    repository, _ = _repo(tmp_path, count=11)
    for index in range(10):
        soloq.register_analysis(repository, f"EUW1_{1000 + index}")
    with pytest.raises(ValueError, match="10"): 
        soloq.register_analysis(repository, "EUW1_1010")
    assert soloq.list_analyses(repository)["count"] == 10
    assert len(repository.load(repository.load_last_profile())["matches"]) == 11



def test_saved_analysis_limit_is_independent_from_companion_sessions(monkeypatch, tmp_path: Path):
    repository, _ = _repo(tmp_path)
    monkeypatch.setattr(soloq, "_legacy_saved_count", lambda: 10)
    registered = soloq.register_analysis(repository, "EUW1_1000")
    assert registered["match_id"] == "EUW1_1000"
    assert len(repository.load_saved_analyses(repository.load_last_profile())) == 1


def test_clear_home_history_preserves_explicit_soloq_analyses(tmp_path: Path):
    repository, profile = _repo(tmp_path)
    soloq.register_analysis(repository, "EUW1_1000")
    repository.clear(profile)
    assert repository.load(profile)["matches"] == []
    assert [item["match_id"] for item in repository.load_saved_analyses(profile)] == ["EUW1_1000"]


def test_download_normalizes_real_riot_roster_and_timeline(monkeypatch, tmp_path: Path):
    repository, profile = _repo(tmp_path)
    soloq.register_analysis(repository, "EUW1_1000")
    monkeypatch.setattr(soloq.SettingsService, "load", lambda self: {"riot_api_key": "fixture-key"})

    class Cache:
        timeline = None
        raw = None
        detail = None
        def rate_limit_remaining_seconds(self): return 0
        def get_match(self, match_id, puuid): return self.detail if self.detail and self.detail.get("player_puuid") == puuid else None
        def save_match(self, detail, puuid): self.detail = {**detail, "player_puuid": puuid}
        def get_raw_match(self, match_id): return self.raw
        def save_raw_match(self, match_id, value): self.raw = value
        def get_timeline(self, match_id): return self.timeline
        def save_timeline(self, match_id, timeline): self.timeline = timeline

    cache = Cache()
    class FakeApi:
        _create_match_detail = staticmethod(RiotApiService._create_match_detail)
        def __init__(self, *_args, **_kwargs): self.cache = cache
        def get_match(self, match_id):
            return {"metadata": {"matchId": match_id}, "info": {
                "queueId": 420, "gameCreation": 1792480000000, "gameDuration": 1800,
                "gameMode": "CLASSIC", "gameVersion": "16.20.1",
                "participants": [
                    {"participantId": 1, "puuid": "local-puuid", "teamId": 100, "championId": 233, "championName": "Briar", "teamPosition": "JUNGLE", "win": True, "kills": 5, "deaths": 3, "assists": 4, "totalMinionsKilled": 10, "neutralMinionsKilled": 120, "goldEarned": 12000, "visionScore": 20, "champLevel": 16, "item0": 3006},
                    {"participantId": 6, "puuid": "enemy-puuid", "teamId": 200, "championId": 24, "championName": "Jax", "teamPosition": "TOP", "win": False, "kills": 3, "deaths": 5, "assists": 2, "totalMinionsKilled": 180, "goldEarned": 11000, "visionScore": 15, "champLevel": 15, "item0": 3078},
                ], "teams": [{"teamId": 100, "objectives": {}}, {"teamId": 200, "objectives": {}}],
            }}
        def get_match_timeline(self, match_id):
            value = {"info": {"frames": [{"timestamp": 600000, "participantFrames": {"1": {"totalGold": 5000, "level": 10}}, "events": [
                {"type": "CHAMPION_KILL", "timestamp": 600000, "killerId": 6, "victimId": 1, "assistingParticipantIds": []},
            ]}]}}
            cache.save_timeline(match_id, value)
            return value

    monkeypatch.setattr(soloq, "RiotApiService", FakeApi)
    ready = soloq.download_match(repository, "EUW1_1000")
    assert ready["status"] == "ready"
    assert ready["timeline_available"] is True
    assert next(player for player in ready["participants"] if player["local"])["champion"] == "Briar"
    event = ready["events"][0]
    assert event["killerChampion"] == "Jax" and event["victimChampion"] == "Briar"
    assert event["side"] == "enemy"
    assert ready["frames"][0]["gold"] == 5000
    score = next(player for player in ready["participants"] if player["participantId"] == 1)
    assert ready["battle_score"]["version"] == "battlescore_v2_7"
    assert score["battleScoreSeries"][0] == {"timestamp": 0, "score": 5.0}
    assert score["battleScoreSeries"][-1]["timestamp"] == 1_800_000
    saved = repository.load_saved_analyses(profile)[0]
    assert saved["battle_score"]["version"] == "battlescore_v2_7"
    # Legacy records can lack the participant-local flag; the analyzed
    # champion ID remains a deterministic fallback for comparison summaries.
    for player in saved["participants"]:
        player["local"] = False
    repository.save_soloq_analysis(profile, saved)
    summary = soloq.list_analyses(repository)["matches"][0]
    assert summary["battleScoreVersion"] == "battlescore_v2_7"
    assert isinstance(summary["battleScore"], (int, float))
    assert summary["battleScoreState"] == "partial"


def test_stale_local_puuid_refreshes_via_account_v1_and_reuses_cached_match(monkeypatch, tmp_path: Path):
    repository, profile = _repo(tmp_path)
    soloq.register_analysis(repository, "EUW1_1000")
    monkeypatch.setattr(soloq.SettingsService, "load", lambda self: {"riot_api_key": "fixture-key"})

    class Cache:
        raw = detail = timeline = None
        match_downloads = 0
        def rate_limit_remaining_seconds(self): return 0
        def get_match(self, _match_id, puuid):
            return self.detail if self.detail and self.detail.get("player_puuid") == puuid else None
        def save_match(self, value, puuid): self.detail = {**value, "player_puuid": puuid}
        def get_raw_match(self, _match_id): return self.raw
        def save_raw_match(self, _match_id, value): self.raw = value
        def get_timeline(self, _match_id): return self.timeline
        def save_timeline(self, _match_id, value): self.timeline = value

    cache = Cache()
    payload = {"metadata": {"matchId": "EUW1_1000"}, "info": {
        "queueId": 420, "gameCreation": 1792480000000, "gameDuration": 1800, "gameMode": "CLASSIC",
        "participants": [
            {"participantId": index, "puuid": "fresh-puuid" if index == 1 else f"enemy-{index}", "teamId": 100 if index <= 5 else 200,
             "championId": 233 if index == 1 else 24, "championName": "Briar" if index == 1 else "Jax",
             "teamPosition": "JUNGLE", "win": index <= 5, "kills": 5, "deaths": 3, "assists": 4}
            for index in range(1, 11)
        ], "teams": [{"teamId": 100}, {"teamId": 200}],
    }}
    timeline = {"metadata": {"matchId": "EUW1_1000"}, "info": {"frames": [{"timestamp": 0, "events": []}]}}

    class FakeApi:
        _create_match_detail = staticmethod(RiotApiService._create_match_detail)
        def __init__(self, *_args, **_kwargs): self.cache = cache
        def get_match(self, _match_id): cache.match_downloads += 1; return payload
        def get_account_by_riot_id(self, *_args, **_kwargs): return {"puuid": "fresh-puuid"}
        def get_match_timeline(self, _match_id): cache.save_timeline(_match_id, timeline); return timeline

    monkeypatch.setattr(soloq, "RiotApiService", FakeApi)
    ready = soloq.download_match(repository, "EUW1_1000")
    assert ready["status"] == "ready"
    assert ready["local_identity_resolved"] is True
    assert len(ready["participants"]) == 10
    assert sum(1 for participant in ready["participants"] if participant["local"]) == 1
    migrated_profile = repository.load_last_profile()
    assert migrated_profile["riot_puuid"] == "fresh-puuid"
    assert migrated_profile["puuid"] == "fresh-puuid"
    assert len(repository.load_saved_analyses(migrated_profile)) == 1
    assert len(repository.load(migrated_profile)["matches"]) == 1
    reopened = soloq.download_match(repository, "EUW1_1000")
    assert reopened["status"] == "ready"
    assert cache.match_downloads == 1


def test_unresolved_local_identity_preserves_valid_roster_without_fabricating_local():
    raw = {"metadata": {"matchId": "EUW1_1"}, "info": {
        "queueId": 420, "participants": [
            {"participantId": index, "puuid": f"other-{index}", "teamId": 100 if index <= 5 else 200,
             "championName": f"Champion{index}", "win": index <= 5}
            for index in range(1, 11)
        ], "teams": [{"teamId": 100}, {"teamId": 200}],
    }}
    detail = RiotApiService._create_match_detail(raw, "EUW1_1", "stale-puuid", allow_unresolved=True)
    assert detail["player_resolved"] is False
    assert len(detail["allies"] + detail["enemies"]) == 10
    assert not any(player["is_player"] for player in detail["allies"] + detail["enemies"])


def test_euw1_match_routes_to_europe_and_region_prefix_must_match():
    assert soloq._routing("EUW1") == ("europe", "euw1")


def test_timeline_keeps_small_and_full_item_transactions_and_applies_undo():
    roster = [{"participantId": 1, "champion": "Briar", "side": "allied"}]
    timeline = {"info": {"frames": [{"timestamp": 1000, "events": [
        {"type": "ITEM_PURCHASED", "timestamp": 1000, "participantId": 1, "itemId": 1001},
        {"type": "ITEM_PURCHASED", "timestamp": 2000, "participantId": 1, "itemId": 3006},
        {"type": "ITEM_UNDO", "timestamp": 3000, "participantId": 1, "beforeId": 3006, "afterId": 0},
        {"type": "ITEM_PURCHASED", "timestamp": 4000, "participantId": 1, "itemId": 3006},
        {"type": "ITEM_SOLD", "timestamp": 5000, "participantId": 1, "itemId": 3006},
    ]}]}}
    events, _ = soloq._normalize_events(timeline, roster)
    assert [(event["type"], event["itemId"]) for event in events] == [
        ("ITEM_PURCHASED", 1001), ("ITEM_PURCHASED", 3006), ("ITEM_SOLD", 3006)
    ]


def test_ai_analysis_is_explicitly_persisted_and_reused(monkeypatch, tmp_path: Path):
    repository, profile = _repo(tmp_path)
    record = soloq.register_analysis(repository, "EUW1_1000")
    record.update({"status": "ready", "participants": [{
        "participantId": 1, "local": True, "side": "allied", "champion": "Briar", "role": "JUNGLE",
        "kills": 5, "deaths": 3, "assists": 4, "cs": 130, "gold": 12000, "vision": 20,
        "damage": 30000, "damageToObjectives": 4000, "items": [3006],
    }], "events": []})
    repository.save_soloq_analysis(profile, record)
    monkeypatch.setattr(soloq.SettingsService, "load", lambda self: {"gemini_api_key": "fixture-key"})
    calls = []
    class FakeAnalyzer:
        def analyze_match(self, session, api_key):
            calls.append((session["session_id"], bool(api_key)))
            from app.services.match_analysis_evidence_service import MatchAnalysisEvidenceService
            from app.services.match_analysis_models import enriquecer_analisis_partida
            local_key = str(session["local_player_key"])
            evidence_context = {
                "metadata": {"duration_seconds": session["duration"], "local_team": session["local_team"]},
                "local_player_key": local_key,
                "user_stats": {"champion": session["champion_name"]},
                "all_players": [{"player_key": local_key, "champion": session["champion_name"],
                                 "team": session["local_team"], "is_ally": True}],
                "events_chronology": [],
            }
            evidence = MatchAnalysisEvidenceService().build_evidence(evidence_context)
            analysis = enriquecer_analisis_partida({
                "schema_version": 3, "analysis_type": "general_match_analysis",
                "summary": {"short_summary": "Fixture"}, "key_events": [],
            }, {**evidence_context, "analysis_evidence": evidence})
            return analysis, "{}", "fixture-model", "fingerprint"
    monkeypatch.setattr("app.services.match_ai_analyzer_service.MatchAIAnalyzerService", FakeAnalyzer)
    first = soloq.generate_ai_analysis(repository, "EUW1_1000")
    second = soloq.generate_ai_analysis(repository, "EUW1_1000")
    assert first["ai_analysis"]["analysis"]["summary"]["short_summary"] == "Fixture"
    assert first["ai_analysis"]["analysis"]["match_evidence"]["evidence_version"] == 6
    assert second["ai_analysis"]["provider"] == "Gemini"
    assert calls == [("EUW1_1000", True)]


def test_failed_ai_regeneration_preserves_previous_report_and_event_index(monkeypatch, tmp_path: Path):
    class EmptyCache:
        def get_timeline(self, _match_id): return None
        @staticmethod
        def get_raw_match(_match_id): return None
    monkeypatch.setattr(soloq, "MatchHistoryCache", EmptyCache)
    monkeypatch.setattr(soloq, "_role_phase_references", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(soloq, "_attach_battlescore", lambda *_args, **_kwargs: {"state": "partial"})
    repository, profile = _repo(tmp_path)
    previous = {
        "analysis": {"schema_version": 3, "analysis_type": "general_match_analysis",
                     "summary": {"short_summary": "Informe anterior válido."}},
        "provider": "Gemini", "model": "previous-model", "created_at": "2026-10-20T10:00:00Z",
    }
    record = soloq.register_analysis(repository, "EUW1_1000")
    record.update({
        "status": "ready", "timeline_available": True,
        "participants": [{"participantId": 1, "local": True, "side": "allied",
                          "teamId": 100, "champion": "Briar", "role": "JUNGLE"}],
        "events": [{"id": "0:0:600000", "timestamp": 600000, "type": "CHAMPION_KILL",
                    "category": "Asesinato", "side": "allied", "killerId": 1, "victimId": 6,
                    "assistingIds": [], "killerTeamId": 100}],
        "frames": [{"timestamp": 600000}], "ai_analysis": previous,
    })
    repository.save_soloq_analysis(profile, record)
    monkeypatch.setattr(soloq.SettingsService, "load", lambda self: {"gemini_api_key": "fixture-key"})

    class FailingAnalyzer:
        def analyze_match(self, *_args):
            raise ValueError("respuesta inválida de prueba")

    monkeypatch.setattr("app.services.match_ai_analyzer_service.MatchAIAnalyzerService", FailingAnalyzer)

    with pytest.raises(ValueError, match="respuesta inválida"):
        soloq.generate_ai_analysis(repository, "EUW1_1000", force=True)

    saved = repository.load_saved_analyses(profile)[0]
    assert saved["ai_analysis"]["model"] == "previous-model"
    assert saved["ai_analysis"]["analysis"]["summary"]["short_summary"] == "Informe anterior válido."
    assert saved["timeline_event_index"]["notable_timeline"]
