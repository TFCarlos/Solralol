from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.live_match_tracker import LiveMatchTracker
from backend import saved_matches


def _session(index: int) -> dict:
    started = datetime(2026, 10, 1, tzinfo=UTC) + timedelta(days=index)
    key = f"participant-{index}"
    return {
        "schema_version": 2,
        "session_id": f"saved-{index}",
        "started_at": started.isoformat(),
        "ended_at": (started + timedelta(minutes=30)).isoformat(),
        "duration": 1800,
        "game_mode": "CLASSIC",
        "local_team": "ORDER",
        "local_player_key": key,
        "champion_name": "Briar",
        "players": {key: {"champion_name": "Briar", "role": "JUNGLE", "team": "ORDER", "champion_id": 233}},
        "final_scoreboard": {key: {"kills": 5, "deaths": 3, "assists": 4, "win": True}},
        "events": [],
        "snapshots": [{"time": 10, "players": {key: {"kills": index}}}],
        "ai_match_analysis": {"analysis": {"summary": {"short_summary": "guardado"}}} if index == 1 else None,
    }


def _temp_tracker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LiveMatchTracker:
    tracker = LiveMatchTracker({}, persist=False)
    tracker.sessions_path = tmp_path / "live_match_sessions.json"
    monkeypatch.setattr(saved_matches, "_tracker", lambda: tracker)
    return tracker


def test_list_keeps_legacy_collection_over_ten_without_trimming(tmp_path, monkeypatch):
    tracker = _temp_tracker(tmp_path, monkeypatch)
    tracker._save_sessions([_session(index) for index in range(12)], replace=True)
    from app.services.home_history_service import HomeHistoryRepository
    monkeypatch.setattr("app.services.home_history_service.HomeHistoryRepository", lambda: _EmptyHistoryRepository())

    result = saved_matches.list_saved_matches()

    assert result["count"] == 12
    assert result["limit"] == 10
    assert result["overLimit"] is False
    assert result["analysisCount"] == 0
    assert result["matches"][0]["champion"] == "Briar"
    assert result["matches"][0]["win"] is True
    assert result["matches"][0]["analysisAvailable"] is False
    assert len(tracker.load_saved_sessions_checked()) == 12


class _EmptyHistoryRepository:
    def load_last_profile(self): return None


def test_detail_reuses_saved_session_and_existing_ai_record(tmp_path, monkeypatch):
    tracker = _temp_tracker(tmp_path, monkeypatch)
    tracker._save_sessions([_session(1)], replace=True)

    result = saved_matches.get_saved_match("saved-1")

    assert result["summary"]["champion"] == "Briar"
    assert result["summary"]["kills"] == 5
    assert result["sessionId"] == "saved-1"
    assert result["matchAnalysis"]["analysis"]["summary"]["short_summary"] == "guardado"


def test_delete_cascades_saved_session_and_unlinks_home_reference(tmp_path, monkeypatch):
    tracker = _temp_tracker(tmp_path, monkeypatch)
    tracker._save_sessions([_session(1), _session(2)], replace=True)
    unlinked = []
    monkeypatch.setattr(LiveMatchTracker, "_delete_match_logs", staticmethod(lambda _ids: None))
    def cascade(*, session_id, manifest_id):
        assert session_id == "saved-1"
        assert manifest_id == "a" * 64
        tracker.delete_saved_session(session_id)
        unlinked.append(session_id)
        return {"deleted": True, "recordingDeleted": False, "warnings": []}
    monkeypatch.setattr("backend.match_deletion.delete_saved_match_footprint", cascade)

    result = saved_matches.delete_saved_match("saved-1", "a" * 64)

    assert result == {"deleted": True, "count": 1}
    assert [item["session_id"] for item in tracker.load_saved_sessions_checked()] == ["saved-2"]
    assert unlinked == ["saved-1"]


def test_corrupt_repository_is_reported_instead_of_as_empty(tmp_path, monkeypatch):
    tracker = _temp_tracker(tmp_path, monkeypatch)
    tracker.sessions_path.write_text("{bad json", encoding="utf-8")
    with patch.object(saved_matches, "_tracker", return_value=tracker):
        with pytest.raises(json.JSONDecodeError):
            saved_matches.list_saved_matches()
