from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.match_history_cache import MatchHistoryCache
from backend import match_deletion


class _Tracker:
    sessions = [
        {"session_id": "session-1", "match_id": "EUW1_1"},
        {"session_id": "session-other", "match_id": "EUW1_OTHER"},
    ]

    def __init__(self, *_args, **_kwargs):
        pass

    def load_saved_sessions(self):
        return list(self.sessions)

    def delete_saved_session(self, session_id):
        type(self).sessions = [item for item in type(self).sessions if item["session_id"] != session_id]


class _Repository:
    def __init__(self):
        self.profile = {"puuid": "private-profile-id"}
        self.analyses = [
            {"match_id": "EUW1_1", "history_match_id": "EUW1_1", "ai_analysis": {"summary": "saved"}},
            {"match_id": "EUW1_OTHER", "history_match_id": "EUW1_OTHER", "ai_analysis": {"summary": "keep"}},
        ]
        self.unlinked = []
        self.deleted = []

    def load_last_profile(self):
        return self.profile

    def load_saved_analyses(self, _profile):
        return list(self.analyses)

    def load(self, _profile):
        return {"matches": [{"stable_match_id": "EUW1_1", "saved_match_link": {"saved_match_id": "session-1"}, "performance_summary": {"kda": 5}}]}

    def unlink_saved_match(self, _profile, session_id):
        self.unlinked.append(session_id)


class _Settings:
    def load(self):
        return {"recording_output_dir": str(_Library.directory)}


class _Library:
    videos: list[Path] = []
    metadata: dict[str, dict] = {}
    deleted: list[str] = []
    fail_delete = False
    directory: Path

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else type(self).directory

    def video_files(self):
        return list(self.videos)

    def load_metadata(self, path):
        return self.metadata.get(path.name, {})

    @staticmethod
    def metadata_path(path):
        return Path(path).with_suffix(".json")

    def delete(self, path):
        if self.fail_delete:
            return False
        self.deleted.append(path.name)
        path.unlink(missing_ok=True)
        self.metadata_path(path).unlink(missing_ok=True)
        cache = self.directory / ".seek_cache"
        if cache.is_dir():
            for item in cache.glob(f"{path.name}.*.seek.mp4"):
                item.unlink(missing_ok=True)
        thumb_key = hashlib.sha256(str(Path(path).resolve()).casefold().encode("utf-8")).hexdigest()
        thumbs = Path.home() / ".solralol" / "recording-thumbnails"
        if thumbs.is_dir():
            for item in thumbs.glob(f"{thumb_key}.*.jpg"):
                item.unlink(missing_ok=True)
        return True


@pytest.fixture
def cleanup_world(monkeypatch, tmp_path):
    _Tracker.sessions = [
        {"session_id": "session-1", "match_id": "EUW1_1"},
        {"session_id": "session-other", "match_id": "EUW1_OTHER"},
    ]
    _Library.videos = []
    _Library.directory = tmp_path
    _Library.metadata = {}
    _Library.deleted = []
    _Library.fail_delete = False
    repo = _Repository()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(match_deletion, "HomeHistoryRepository", lambda: repo)
    monkeypatch.setattr(match_deletion, "LiveMatchTracker", _Tracker)
    monkeypatch.setattr(match_deletion, "SettingsService", _Settings)
    monkeypatch.setattr(match_deletion, "RecordingLibrary", _Library)
    class Cache:
        data = {"matches": {}, "raw_matches": {}, "timelines": {}}
        def delete_match_data(self, key):
            repo.deleted.append(key)
            return True
    monkeypatch.setattr(match_deletion, "MatchHistoryCache", Cache)
    from app.services.match_log_service import MatchLogService
    monkeypatch.setattr(MatchLogService, "delete_match_log", lambda _self, _key: None)
    def delete_analysis(_repo, key):
        before = len(repo.analyses)
        repo.analyses = [item for item in repo.analyses if item["match_id"] != key]
        if len(repo.analyses) != before:
            repo.deleted.append(f"analysis:{key}")
            return True
        return False
    monkeypatch.setattr("backend.soloq_analyses.delete_analysis", delete_analysis)
    return repo, tmp_path


def test_cascade_removes_linked_recording_riot_cache_and_ai_but_keeps_other_match(cleanup_world):
    repo, tmp_path = cleanup_world
    linked = tmp_path / "match.mp4"
    unrelated = tmp_path / "other.mp4"
    linked.write_bytes(b"video")
    unrelated.write_bytes(b"other")
    _Library.videos = [linked, unrelated]
    _Library.metadata = {"match.mp4": {"session_id": "session-1"}, "other.mp4": {"session_id": "session-other"}}

    manifest = match_deletion.preview_saved_match_deletion(match_id="EUW1_1")
    result = match_deletion.delete_saved_match_footprint(match_id="EUW1_1", manifest_id=manifest["manifestId"])

    assert result == {"deleted": True, "recordingDeleted": True, "warnings": []}
    assert not linked.exists()
    assert unrelated.exists()
    assert [item["session_id"] for item in _Tracker.sessions] == ["session-other"]
    assert repo.unlinked == ["session-1"]
    assert "analysis:EUW1_1" in repo.deleted
    assert "EUW1_1" in repo.deleted
    assert [item["match_id"] for item in repo.analyses] == ["EUW1_OTHER"]
    assert repo.profile == {"puuid": "private-profile-id"}


def test_preview_lists_real_file_names_and_sizes_without_mutating_files(cleanup_world, monkeypatch):
    _repo, tmp_path = cleanup_world
    video = tmp_path / "Briar-match.mp4"
    video.write_bytes(b"12345")
    sidecar = tmp_path / "Briar-match.json"
    sidecar.write_text('{"session_id":"session-1"}', encoding="utf-8")
    _Library.videos = [video]
    _Library.metadata = {video.name: {"session_id": "session-1"}}
    seek_dir = tmp_path / ".seek_cache"
    seek_dir.mkdir()
    seek = seek_dir / "Briar-match.mp4.abc.seek.mp4"
    seek.write_bytes(b"123")
    thumb_dir = tmp_path / ".solralol" / "recording-thumbnails"
    thumb_dir.mkdir(parents=True)
    monkeypatch.setattr(match_deletion, "get_storage_manager", lambda: SimpleNamespace(
        recording_thumbnails_dir=thumb_dir, match_logs_dir=tmp_path / "logs",
    ))
    key = hashlib.sha256(str(video.resolve()).casefold().encode("utf-8")).hexdigest()
    thumb = thumb_dir / f"{key}.320x180.jpg"
    thumb.write_bytes(b"12")

    manifest = match_deletion.preview_saved_match_deletion(match_id="EUW1_1")

    files = [resource for resource in manifest["resources"] if resource["kind"] == "file"]
    assert {resource["name"] for resource in files} == {video.name, sidecar.name, seek.name, thumb.name}
    assert manifest["summary"]["files"] == 4
    expected_file_bytes = 5 + sidecar.stat().st_size + 3 + 2
    expected_record_bytes = sum(resource["size"] or 0 for resource in manifest["resources"] if resource["kind"] == "record")
    assert manifest["summary"]["bytes"] == expected_file_bytes + expected_record_bytes
    assert expected_record_bytes > 0
    assert all(path.exists() for path in (video, sidecar, seek, thumb))
    assert any(item["name"] == "Perfil persistente del jugador" for item in manifest["preserved"])

    result = match_deletion.delete_saved_match_footprint(match_id="EUW1_1", manifest_id=manifest["manifestId"])
    assert result["deleted"] is True
    assert all(not path.exists() for path in (video, sidecar, seek, thumb))


def test_preview_lists_match_v5_and_timeline_records_as_local_data(cleanup_world, monkeypatch):
    _repo, _tmp_path = cleanup_world

    class Cache:
        data = {
            "matches": {"EUW1_1:profile": {"participants": [1]}},
            "raw_matches": {"EUW1_1": {"info": {"gameId": 1}}},
            "timelines": {"EUW1_1": {"info": {"frames": []}}},
        }

    monkeypatch.setattr(match_deletion, "MatchHistoryCache", Cache)
    manifest = match_deletion.preview_saved_match_deletion(match_id="EUW1_1")

    riot_resources = [resource for resource in manifest["resources"] if resource["category"] == "riot"]
    names = {resource["name"] for resource in riot_resources}
    assert "Datos de partida procesados · EUW1_1" in names
    assert "Respuesta Match-V5 · EUW1_1" in names
    assert "Cronología Match-V5 · EUW1_1" in names
    assert all(resource["kind"] == "record" for resource in riot_resources)
    assert all(resource["size"] > 0 for resource in riot_resources)
    assert any(item["name"] == "Historial oficial de Riot" for item in manifest["preserved"])


def test_match_id_preview_does_not_list_unassociated_history_as_preserved(cleanup_world):
    repo, _ = cleanup_world
    repo.load = lambda _profile: {"matches": [
        {"stable_match_id": f"EUW1_HISTORY_{index}", "saved_match_link": {"saved_match_id": ""}}
        for index in range(30)
    ]}

    manifest = match_deletion.preview_saved_match_deletion(match_id="EUW1_1")

    assert not any("sin vínculo exacto" in item["name"].lower() for item in manifest["preserved"])


def test_uncertain_history_for_session_is_summarized_once(cleanup_world):
    repo, _ = cleanup_world
    repo.load = lambda _profile: {"matches": [
        {"stable_match_id": f"EUW1_HISTORY_{index}", "saved_match_link": {
            "saved_match_id": "session-1", "association": "approximate",
        }}
        for index in range(30)
    ]}

    manifest = match_deletion.preview_saved_match_deletion(session_id="session-1")
    uncertain = [item for item in manifest["preserved"] if "sin vínculo exacto" in item["name"].lower()]

    assert len(uncertain) == 1
    assert "30 partidas" in uncertain[0]["name"]


def test_preview_preserves_recording_referenced_by_multiple_sessions(cleanup_world, tmp_path):
    _repo, _ = cleanup_world
    _Tracker.sessions = [
        {"session_id": "session-1", "match_id": "EUW1_1", "recording_id": "shared-recording"},
        {"session_id": "session-other", "match_id": "EUW1_OTHER", "recording_id": "shared-recording"},
    ]
    video = tmp_path / "shared.mp4"
    video.write_bytes(b"shared")
    _Library.videos = [video]
    _Library.metadata = {video.name: {"session_id": "session-1", "recording_id": "shared-recording"}}

    manifest = match_deletion.preview_saved_match_deletion(match_id="EUW1_1")

    assert video.name not in {item["name"] for item in manifest["resources"]}
    assert any(item["name"] == video.name and item["type"].startswith("Grabaci") for item in manifest["preserved"])
    assert video.exists()


def test_delete_modal_source_uses_utf8_spanish_text_without_literal_escapes():
    root = Path(__file__).resolve().parents[1]
    modal = (root / "frontend/src/components/ConfirmModal.tsx").read_text(encoding="utf-8")
    page = (root / "frontend/src/pages/SavedMatchesPage.tsx").read_text(encoding="utf-8")
    description = next(line for line in page.splitlines() if "pendingDelete && <ConfirmModal" in line)
    assert chr(0xbf) + "Eliminar esta partida guardada?" in description
    assert "Tambi" + chr(0xe9) + "n se eliminar" + chr(0xe1) + "n" in description
    assert "\\u00" not in description and "\\u00" not in modal
    assert chr(0xfffd) not in description and chr(0xfffd) not in modal


def test_confirmation_rejects_manifest_if_file_changes_after_preview(cleanup_world, tmp_path):
    _repo, _ = cleanup_world
    video = tmp_path / "match.mp4"
    video.write_bytes(b"one")
    _Library.videos = [video]
    _Library.metadata = {video.name: {"session_id": "session-1"}}
    manifest = match_deletion.preview_saved_match_deletion(match_id="EUW1_1")
    video.write_bytes(b"changed-size")

    with pytest.raises(ValueError, match="cambiaron desde la vista previa"):
        match_deletion.delete_saved_match_footprint(match_id="EUW1_1", manifest_id=manifest["manifestId"])
    assert video.exists()
    assert any(item["session_id"] == "session-1" for item in _Tracker.sessions)


def test_cascade_succeeds_without_optional_recording(cleanup_world):
    repo, _ = cleanup_world
    manifest = match_deletion.preview_saved_match_deletion(match_id="EUW1_1")
    result = match_deletion.delete_saved_match_footprint(match_id="EUW1_1", manifest_id=manifest["manifestId"])
    assert result["deleted"] is True
    assert result["recordingDeleted"] is False
    assert "analysis:EUW1_1" in repo.deleted


def test_recording_failure_does_not_remove_saved_match(cleanup_world, tmp_path):
    _repo, _ = cleanup_world
    video = tmp_path / "locked.mp4"
    video.write_bytes(b"video")
    _Library.videos = [video]
    _Library.metadata = {"locked.mp4": {"session_id": "session-1"}}
    _Library.fail_delete = True

    with pytest.raises(ValueError, match="No se pudo eliminar la grabación"):
        manifest = match_deletion.preview_saved_match_deletion(match_id="EUW1_1")
        match_deletion.delete_saved_match_footprint(match_id="EUW1_1", manifest_id=manifest["manifestId"])
    assert video.exists()
    assert any(item["session_id"] == "session-1" for item in _Tracker.sessions)


def test_match_history_cache_deletes_only_exact_match_scoped_entries(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({
        "version": 2,
        "accounts": {"profile": {"puuid": "keep"}},
        "matches": {"EUW1_1": {"data": 1}, "EUW1_1:puuid": {"data": 2}, "EUW1_10:puuid": {"data": 3}},
        "raw_matches": {"EUW1_1": {"match": {}}, "EUW1_OTHER": {"match": {}}},
        "timelines": {"EUW1_1": {"timeline": {}}, "EUW1_OTHER": {"timeline": {}}},
    }), encoding="utf-8")
    cache = object.__new__(MatchHistoryCache)
    cache.cache_path = path

    assert cache.delete_match_data("EUW1_1") is True
    result = json.loads(path.read_text(encoding="utf-8"))
    assert result["accounts"]["profile"]["puuid"] == "keep"
    assert result["matches"] == {"EUW1_10:puuid": {"data": 3}}
    assert list(result["raw_matches"]) == ["EUW1_OTHER"]
    assert list(result["timelines"]) == ["EUW1_OTHER"]
