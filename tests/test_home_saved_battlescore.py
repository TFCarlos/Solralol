from __future__ import annotations

from backend.analysis_settings import engine_snapshot, load_configuration
from backend.battlescore import VERSION
from backend.home_battlescore import attach_saved_battlescores
from app.services.home_dashboard_analytics import build_ranked_dashboard_analytics
from backend.application import _serialize_home_matches
from app.services.home_history_service import HomeHistoryRepository


HASH = engine_snapshot(load_configuration())["configuration_hash"]
PROFILE = {"riot_puuid": "verified-player"}


def match(number, role="jungle", queue=420):
    return {"stable_match_id": f"EUW1_{number}", "game_id": f"EUW1_{number}",
            "queue_id": queue, "lane": role, "result": "victory", "started_at": f"2026-01-{number:02d}T12:00:00Z"}


def record(number, score, *, local=2, history_id=None):
    return {"match_id": f"EUW1_{number}", "history_match_id": history_id or f"EUW1_{number}",
            "queue_id": 420, "local_identity_resolved": True,
            "participants": [{"participantId": 1, "local": local == 1}, {"participantId": 2, "local": local == 2}],
            "battle_score": {"version": VERSION, "configurationHash": HASH, "state": "partial",
                             "matchId": f"EUW1_{number}", "participants": [
                                 {"participantId": 1, "state": "complete", "finalScore": 9.9},
                                 {"participantId": 2, "state": "partial", "finalScore": score}]}}


def test_home_uses_verified_local_participant_and_stable_match_id():
    matches = [match(1), match(2), match(3)]
    records = [record(1, 6.2), record(2, 4.5)]
    joined = attach_saved_battlescores(matches, records, PROFILE)
    assert [row.get("battle_score") for row in joined] == [6.2, 4.5, None]
    assert matches[0].get("battle_score") is None
    public = _serialize_home_matches(joined, 0, 3, saved_analyses=records)
    assert public[0]["battle_score"] == 6.2
    assert "battle_score_verified" not in public[0]


def test_home_average_uses_only_scored_unique_soloq_matches_by_role(monkeypatch):
    from app.services import home_dashboard_analytics as analytics
    monkeypatch.setattr(analytics, "_local_champion_metadata", dict)
    matches = [match(1), match(1), match(2, "mid"), match(3), match(4, queue=440)]
    records = [record(1, 6.2), record(2, 7.6), record(3, 4.5), record(4, 8.8)]
    joined = attach_saved_battlescores(matches, records, PROFILE)
    stats = build_ranked_dashboard_analytics(joined)["stats_by_role"]
    assert stats["all"]["performance_score"]["value"] == 6.1
    assert stats["all"]["performance_score"]["sample"] == 3
    assert stats["jungle"]["performance_score"]["value"] == 5.4
    assert stats["jungle"]["performance_score"]["sample"] == 2
    assert stats["mid"]["performance_score"]["value"] == 7.6


def test_missing_deleted_and_zero_scores_are_handled(monkeypatch):
    from app.services import home_dashboard_analytics as analytics
    monkeypatch.setattr(analytics, "_local_champion_metadata", dict)
    matches = [match(1), match(2)]
    records = [record(1, 0), record(2, 8)]
    scored = attach_saved_battlescores(matches, records, PROFILE)
    assert build_ranked_dashboard_analytics(scored)["stats_by_role"]["all"]["performance_score"]["value"] == 4.0
    after_delete = attach_saved_battlescores(matches, records[:1], PROFILE)
    metric = build_ranked_dashboard_analytics(after_delete)["stats_by_role"]["all"]["performance_score"]
    assert metric["value"] == 0.0 and metric["sample"] == 1


def test_corrupt_or_unverified_saved_records_never_supply_a_teammate_score():
    base = record(1, 6.2)
    variants = []
    for change in ({"local_identity_resolved": False}, {"participants": []},
                   {"battle_score": {**base["battle_score"], "matchId": "EUW1_999"}},
                   {"battle_score": {**base["battle_score"], "configurationHash": "stale"}},
                   {"battle_score": {**base["battle_score"], "participants": [{"participantId": 1, "state": "complete", "finalScore": 9.9}]}}):
        variants.append({**base, **change})
    for bad in variants:
        assert attach_saved_battlescores([match(1)], [bad], PROFILE)[0].get("battle_score") is None
    assert attach_saved_battlescores([match(1)], [base], {})[0].get("battle_score") is None


def test_score_survives_repository_reload_and_deletion(tmp_path):
    repository = HomeHistoryRepository(tmp_path)
    saved = record(1, 6.2)
    repository.save_soloq_analysis(PROFILE, saved)
    reopened = HomeHistoryRepository(tmp_path)
    assert attach_saved_battlescores([match(1)], reopened.load_saved_analyses(PROFILE), PROFILE)[0]["battle_score"] == 6.2
    assert reopened.delete_soloq_analysis(PROFILE, "EUW1_1") is True
    assert attach_saved_battlescores([match(1)], reopened.load_saved_analyses(PROFILE), PROFILE)[0].get("battle_score") is None


def test_historical_lcu_id_resolves_to_saved_riot_match_without_rewriting_history():
    old_match = {**match(1), "stable_match_id": "123456", "game_id": "123456"}
    saved = record(1, 6.2, history_id="123456")
    assert attach_saved_battlescores([old_match], [saved], PROFILE)[0]["battle_score"] == 6.2
    assert old_match["stable_match_id"] == "123456"


def test_ambiguous_or_invalid_results_remain_unavailable():
    original = record(1, 6.2)
    conflicting = {**record(2, 7.6), "history_match_id": "EUW1_1"}
    assert attach_saved_battlescores([match(1)], [original, conflicting], PROFILE)[0].get("battle_score") is None
    for value in (float("nan"), float("inf"), -1, 11, True):
        invalid = record(1, value)
        assert attach_saved_battlescores([match(1)], [invalid], PROFILE)[0].get("battle_score") is None
