from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from app.services.live_data_worker import LiveDataWorker
from app.services.home_history_service import HomeHistoryRepository
from app.services.live_match_tracker import LiveMatchTracker
from app.ui.recordings_page import MarkerSlider


def _session(index: int, *, ended: bool = True) -> dict:
    started = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
    return {
        "session_id": f"match-{index}",
        "started_at": started.isoformat(),
        "ended_at": (started + timedelta(hours=1)).isoformat() if ended else None,
        "snapshots": [],
    }


def test_retention_migrates_to_ten_unique_completed_matches(tmp_path):
    tracker = LiveMatchTracker({}, persist=True)
    tracker.sessions_path = tmp_path / "sessions.json"
    tracker.sessions_path.write_text(
        json.dumps(
            [_session(i) for i in range(12)]
            + [_session(11), _session(99, ended=False)]
        ),
        encoding="utf-8",
    )

    retained = tracker.enforce_saved_session_limit()

    assert len(retained) == 10
    assert [item["session_id"] for item in retained] == [
        f"match-{i}" for i in range(11, 1, -1)
    ]
    persisted = json.loads(tracker.sessions_path.read_text(encoding="utf-8"))
    assert [item["session_id"] for item in persisted] == [
        f"match-{i}" for i in range(11, 1, -1)
    ]


def test_save_rejects_unfinished_match(tmp_path):
    tracker = LiveMatchTracker({}, persist=True)
    tracker.sessions_path = tmp_path / "sessions.json"
    with pytest.raises(ValueError, match="completadas"):
        tracker.persist_completed_session(_session(1, ended=False))
    assert not tracker.sessions_path.exists()


def test_worker_emits_final_session_before_game_ended():
    QApplication.instance() or QApplication([])
    worker = LiveDataWorker(item_catalog={})
    snapshot = {
        "game_time": 30,
        "game_mode": "CLASSIC",
        "local_team": "ORDER",
        "local_player": {"championName": "Ahri", "summonerName": "Local"},
        "all_players": [],
        "game_events": [],
    }
    worker._update_tracker(snapshot)
    worker.was_in_game = True
    finished = QSignalSpy(worker.game_finished)
    ended = QSignalSpy(worker.game_ended)

    for _ in range(worker.GAME_END_FAILURE_THRESHOLD):
        worker._handle_snapshot_failure("simulated end")

    assert finished.count() == 1
    assert ended.count() == 1
    session = finished.at(0)[0]
    assert session["ended_at"]
    assert session["session_id"]
    assert session["final_scoreboard"] == {}


def test_delete_match_removes_logs_but_preserves_user_recording(tmp_path, monkeypatch):
    from app.services.match_log_service import MatchLogService

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    for suffix in (".json", ".log"):
        (logs_dir / f"match_match-1{suffix}").write_text("derived", encoding="utf-8")
    monkeypatch.setattr(
        MatchLogService,
        "__init__",
        lambda self: setattr(self, "logs_dir", logs_dir),
    )
    video = tmp_path / "independent-recording.mp4"
    video.write_bytes(b"user recording")
    tracker = LiveMatchTracker({}, persist=True)
    tracker.sessions_path = tmp_path / "sessions.json"
    tracker._save_sessions([_session(1)])

    tracker.delete_saved_session("match-1")

    assert tracker.load_saved_sessions() == []
    assert video.read_bytes() == b"user recording"
    assert not list(logs_dir.iterdir())


def test_delete_match_unlinks_its_home_summary_only(tmp_path):
    repository = HomeHistoryRepository(root=tmp_path / "profiles")
    profile = {"puuid": "local-profile"}
    repository.merge(
        profile,
        [
            {
                "stable_match_id": "history-1",
                "saved_match_link": {"saved_match_id": "match-1", "matched": True},
                "performance_summary": {"battle_score": 900},
                "result": "victory",
            },
            {
                "stable_match_id": "history-2",
                "saved_match_link": {"saved_match_id": "match-2", "matched": True},
                "performance_summary": {"battle_score": 800},
            },
        ],
    )

    assert repository.unlink_saved_match(profile, "match-1")
    history = repository.load(profile)["matches"]

    assert history[0]["stable_match_id"] == "history-1"
    assert history[0]["result"] == "victory"
    assert "saved_match_link" not in history[0]
    assert "performance_summary" not in history[0]
    assert history[1]["saved_match_link"]["saved_match_id"] == "match-2"




def test_timeline_scrub_never_queues_preview_seeks_and_commits_release_once():
    app = QApplication.instance() or QApplication([])
    slider = MarkerSlider()
    slider.setRange(0, 120_000)
    slider.set_markers([], 120_000)
    slider.resize(320, 40)
    slider.show()
    app.processEvents()
    seeks = QSignalSpy(slider.seek_requested)
    start = QPoint(20, slider.height() // 2)
    end = QPoint(slider.width() - 20, slider.height() // 2)

    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=start)
    assert seeks.count() == 0
    for x in range(start.x() + 1, end.x(), 4):
        QTest.mouseMove(slider, QPoint(x, start.y()))
    assert seeks.count() == 0
    assert slider.value() > 0
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)

    assert seeks.count() == 1
    assert seeks.at(seeks.count() - 1)[0] == int(slider._seconds_at(end.x()) * 1000)
    slider.close()
