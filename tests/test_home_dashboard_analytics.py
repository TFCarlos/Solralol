from __future__ import annotations

from datetime import UTC, datetime, timedelta

import backend.application as application_module
from app.services import home_dashboard_analytics as dashboard
from app.services.match_history_cache import MatchHistoryCache
from app.services.riot_api_service import RiotApiService
from backend.application import _serialize_home_matches


def _match(index: int, role: str = "jungle", *, result: str = "victory", queue: int = 420):
    participants = []
    for slot in range(10):
        local = slot == 0
        participants.append({
            "participant_id": slot + 1,
            "team_id": 100 if slot < 5 else 200,
            "is_local": local,
            "champion_id": 64 if local else (11 if slot >= 5 else 64 + slot),
            "champion_name": "Lee Sin" if local else f"Champion {slot}",
            "lane": role if local else "unknown",
            "kills": 2 if local else (2 if slot < 5 else 1),
            "deaths": 3 if local else 2,
            "assists": 4 if local else 1,
            "final_stats": {"total_damage_dealt_to_champions": 60_000, "solo_kills": 2, "cs": 150, "vision_score": 24} if local else {},
        })
    return {
        "stable_match_id": f"EUW1_{index}", "game_id": f"EUW1_{index}",
        "queue_id": queue, "result": result,
        "started_at": (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)).isoformat(),
        "duration_seconds": 1800, "champion_id": 64, "champion_name": "Lee Sin",
        "lane": role, "kills": 2, "deaths": 3, "assists": 4, "cs": 150, "vision_score": 24,
        "participants": participants,
        "enemy_team": [{"champion_id": 11, "champion_name": "Master Yi"}] * 5,
        "performance_summary": {"points": 85, "version": 4, "calibration_version": "2026.10", "state": "POSTGAME_FINAL"},
    }


def test_ranked_dashboard_calculates_real_statistics_and_excludes_other_queues(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", lambda: {
        "64": {"id": "LeeSin", "name": "Lee Sin", "tags": ["Fighter", "Assassin"]},
        "11": {"id": "MasterYi", "name": "Master Yi", "tags": ["Fighter", "Assassin"]},
    })
    matches = [_match(1), _match(1), _match(2, queue=440, result="defeat")]
    result = dashboard.build_ranked_dashboard_analytics(matches)
    stats = result["stats_by_role"]["all"]
    assert result["ranked_match_count"] == 1
    assert stats["kda"]["value"] == 2.0
    assert stats["damage_per_minute"]["value"] == 2000
    assert stats["kill_participation"]["value"] == 60.0
    assert stats["cs_per_minute"]["value"] == 5.0
    assert stats["vision_score"]["value"] == 24
    assert stats["vision_score"]["sample"] == 1
    assert stats["solo_kills_per_match"]["value"] == 2.0
    assert stats["gold_diff_15"]["value"] is None
    assert stats["performance_score"]["value"] is None
    assert result["counter"] is None  # Flex no participa en Tu counter.


def test_role_filter_threshold_is_primary_plus_roles_with_at_least_16_matches(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", dict)
    matches = [_match(i, "jungle") for i in range(16)] + [_match(i + 20, "mid") for i in range(15)]
    result = dashboard.build_ranked_dashboard_analytics(matches)
    assert result["primary_role"] == "jungle"
    assert "mid" not in result["role_options"]
    matches.append(_match(99, "mid"))
    result = dashboard.build_ranked_dashboard_analytics(matches)
    assert "mid" in result["role_options"]


def test_your_counter_counts_an_enemy_champion_once_per_match_and_only_losses(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", lambda: {"11": {"id": "MasterYi", "name": "Master Yi", "tags": []}})
    loss = _match(1, result="defeat")
    loss["enemy_team"] = [{"champion_id": 11, "champion_name": "Master Yi"}] * 5
    win = _match(2, result="victory")
    result = dashboard.build_ranked_dashboard_analytics([loss, win])
    assert result["counter"]["losses"] == 1
    assert result["counter"]["encounters"] == 2
    assert result["counter"]["winrate"] == 50.0


def test_your_counter_uses_only_queue_420_across_mixed_historical_records(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", lambda: {
        "11": {"id": "MasterYi", "name": "Master Yi", "tags": []},
        "99": {"id": "Lux", "name": "Lux", "tags": []},
    })
    soloq_loss = _match(1, result="defeat")
    soloq_win = _match(2, result="victory")
    excluded = [
        _match(3, queue=450, result="defeat"),  # ARAM
        _match(4, queue=440, result="defeat"),  # Ranked Flex
        _match(5, queue=0, result="defeat"),    # Custom/private
        _match(6, queue=400, result="defeat"),  # Normal Draft
    ]
    practice = _match(7, result="defeat")
    practice.pop("queue_id")
    practice["mode"] = "PRACTICETOOL"
    practice["enemy_team"] = [{"champion_id": 99, "champion_name": "Lux"}]
    unknown_queue = _match(8, result="defeat")
    unknown_queue.pop("queue_id")
    unknown_queue["mode"] = "CLASSIC"
    unknown_queue["enemy_team"] = [{"champion_id": 99, "champion_name": "Lux"}]

    history = [soloq_loss, *excluded, practice, unknown_queue, soloq_win]
    analytics_counter = dashboard.build_ranked_dashboard_analytics(history)["counter"]
    direct_counter = dashboard.build_home_counter_summary(history)

    assert analytics_counter == direct_counter
    assert analytics_counter == {
        "champion_id": "MasterYi", "name": "Master Yi", "losses": 1,
        "encounters": 2, "wins": 1, "winrate": 50.0,
    }


def test_your_counter_returns_empty_when_history_has_no_reliably_identified_soloq(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", dict)
    flex = _match(1, queue=440, result="defeat")
    missing = _match(2, result="defeat")
    missing.pop("queue_id")
    missing["mode"] = "CLASSIC"

    assert dashboard.build_ranked_dashboard_analytics([flex, missing])["counter"] is None
    assert dashboard.build_home_counter_summary([flex, missing]) is None


def test_home_match_detail_contract_contains_teams_without_player_identifiers():
    match = _match(1)
    match["participants"][0]["puuid"] = "private-puuid"
    match["participants"][0]["summoner_name"] = "private-name"
    serialized = _serialize_home_matches([match], 0, 1, include_details=True)[0]
    assert len(serialized["participants"]) == 10
    assert serialized["participants"][0]["is_local"] is True
    assert "puuid" not in serialized["participants"][0]
    assert "summoner_name" not in serialized["participants"][0]
    assert serialized["enemy_team"][0]["champion_id"] == 11


def test_performance_evolution_uses_latest_30_unique_soloq_matches_in_order(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", lambda: {"64": {"id": "LeeSin", "name": "Lee Sin"}})
    matches = [_match(i) for i in range(35)]
    matches.extend([_match(34, queue=440), {**matches[34], "champion_name": "Duplicate"}])
    analytics = dashboard.build_ranked_dashboard_analytics(matches)
    points = analytics["performance_evolution"]
    assert len(points) == 30
    assert points[0]["match_id"] == "EUW1_5"
    assert points[-1]["match_id"] == "EUW1_34"
    assert [point["position"] for point in points] == list(range(1, 31))
    assert points[-1]["kda"] == 2.0
    assert points[-1]["cs_per_minute"] == 5.0
    assert points[-1]["damage_per_minute"] == 2000
    assert points[-1]["performance_score"] is None
    assert points[-1]["champion_id"] == "LeeSin"


def test_performance_evolution_leaves_missing_metrics_unavailable_and_rejects_unvalidated_battlescore(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", dict)
    match = _match(1)
    match["deaths"] = 0
    match["duration_seconds"] = 0
    match["cs"] = None
    match["performance_summary"]["calibration_version"] = "old"
    point = dashboard.build_ranked_dashboard_analytics([match])["performance_evolution"][0]
    assert point["kda"] is None
    assert point["cs_per_minute"] is None
    assert point["damage_per_minute"] is None
    assert point["performance_score"] is None


def test_performance_evolution_series_is_available_per_role_without_extra_metrics_fabrication(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", dict)
    jungle = _match(1, "jungle")
    mid = _match(2, "mid")
    analytics = dashboard.build_ranked_dashboard_analytics([jungle, mid])
    assert [point["match_id"] for point in analytics["performance_evolution_by_role"]["jungle"]] == ["EUW1_1"]
    assert [point["match_id"] for point in analytics["performance_evolution_by_role"]["mid"]] == ["EUW1_2"]
    point = analytics["performance_evolution_by_role"]["jungle"][0]
    assert point["role"] == "jungle"
    assert point["kill_participation"] == 60.0
    assert point["solo_kills"] == 2
    assert point["gold_diff_15"] is None
    assert point["vision_score"] == 24


def test_metrics_use_complete_team_kills_damage_and_vision_with_legacy_fallback(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", dict)
    match = _match(1)
    match["participants"][2]["kills"] = None
    match["participants"][2]["deaths"] = 99
    match["participants"][0]["final_stats"].pop("total_damage_dealt_to_champions")
    match["total_damage_dealt_to_champions"] = 30_000
    match["vision_score"] = None
    stats = dashboard.build_ranked_dashboard_analytics([match])["stats_by_role"]["all"]
    assert stats["damage_per_minute"]["value"] == 1000
    assert stats["kill_participation"]["value"] == 60.0
    assert stats["vision_score"]["value"] == 24


def test_gold_diff_uses_nearest_minute_15_frame_and_direct_lane_opponent():
    match = _match(1, "top")
    for index, participant in enumerate(match["participants"]):
        participant["lane"] = "top" if participant["team_id"] == 100 else "unknown"
        participant["puuid"] = f"player-{index + 1}"
    match["participants"][5]["lane"] = "top"
    participant_frames = {str(index): {"totalGold": 10_000 + index * 100} for index in range(1, 11)}
    timeline = {"metadata": {"participants": [f"player-{index}" for index in range(1, 11)]},
                "info": {"frames": [{"timestamp": 900_000, "participantFrames": participant_frames}]}}
    # Local participant is #1; direct top opponent #6 has 10,600 gold.
    assert dashboard.gold_difference_at_15(match, timeline) == -500
    match["duration_seconds"] = 899
    assert dashboard.gold_difference_at_15(match, timeline) is None
    match["duration_seconds"] = 1800
    timeline["info"]["frames"][0]["timestamp"] = 899_000
    assert dashboard.gold_difference_at_15(match, timeline) == -500
    timeline["info"]["frames"][0]["timestamp"] = 869_000
    assert dashboard.gold_difference_at_15(match, timeline) is None


def test_metric_trend_compares_latest_valid_value_to_prior_valid_average():
    points = [{"damage_per_minute": 1000}, {"damage_per_minute": None}, {"damage_per_minute": 1200}]
    assert dashboard._metric_trend(points, "damage_per_minute", 1) == {
        "latest": 1200.0, "previous_average": 1000.0, "delta": 200.0,
        "direction": "positive", "sample": 1, "precision": 1,
    }
    assert dashboard._metric_trend([{"kda": 2.0}, {"kda": 2.0}], "kda", 2)["direction"] == "neutral"
    assert dashboard._metric_trend([{"kda": 1.0}], "kda", 2) is None


def test_gold_difference_averages_signed_values_and_keeps_trend(monkeypatch):
    monkeypatch.setattr(dashboard, "_local_champion_metadata", dict)
    older, latest = _match(1), _match(2)
    older["gold_diff_15"] = -500
    latest["gold_diff_15"] = -100
    stats = dashboard.build_ranked_dashboard_analytics([older, latest])["stats_by_role"]["all"]
    assert stats["gold_diff_15"]["value"] == -300
    assert stats["gold_diff_15"]["trend"]["direction"] == "positive"
    assert stats["gold_diff_15"]["trend"]["delta"] == 400


def test_riot_timeline_cache_returns_saved_timeline_without_network(tmp_path):
    cache = MatchHistoryCache()
    cache.cache_path = tmp_path / "match_history_cache.json"
    timeline = {"metadata": {"matchId": "EUW1_1"}, "info": {"frames": []}}
    cache.save_timeline("EUW1_1", timeline)
    client = RiotApiService("test-key", cache=cache)
    client._request = lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network should not be used"))
    assert client.get_match_timeline("EUW1_1") == timeline


def test_gold_timeline_backfill_processes_at_most_one_missing_match_per_sync(monkeypatch):
    from types import SimpleNamespace

    matches = [_match(1, "top"), _match(2, "top")]
    for index, match in enumerate(matches):
        match["stable_match_id"] = f"EUW1_{index + 1}"
        for participant_index, participant in enumerate(match["participants"]):
            participant["puuid"] = f"p{participant_index}"
            participant["lane"] = "top" if participant["team_id"] == 100 else "unknown"
        match["participants"][5]["lane"] = "top"

    class Repository:
        def load(self, _profile):
            return {"matches": matches}

        def merge(self, _profile, patches):
            for patch in patches:
                target = next(item for item in matches if item["stable_match_id"] == patch["stable_match_id"])
                target.update(patch)

    calls = []

    class TimelineClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_match_timeline(self, match_id):
            calls.append(match_id)
            participant_frames = {str(index): {"totalGold": 10_000 + index * 100} for index in range(1, 11)}
            return {"metadata": {"participants": [f"p{index - 1}" for index in range(1, 11)]},
                    "info": {"frames": [{"timestamp": 900_000, "participantFrames": participant_frames}]}}

    app = application_module.Application.__new__(application_module.Application)
    app.settings = SimpleNamespace(load=lambda: {"riot_api_key": "configured"})
    app._home_repository = Repository()
    monkeypatch.setattr(application_module, "RiotApiService", TimelineClient)
    profile = {"region": "EUW1", "puuid": "local"}
    app._backfill_gold_difference(profile)
    assert len(calls) == 1
    assert sum(match.get("gold_diff_15") is not None for match in matches) == 1
    app._backfill_gold_difference(profile)
    assert len(calls) == 2
