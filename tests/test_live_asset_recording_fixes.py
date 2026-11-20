from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from app.services.game_service import GameService
from app.services.recording_service import RecordingLibrary
from backend.application import Application
from backend.recordings import RecordingRuntime
from backend.draft import DraftRuntime
import pytest


PNG = b"\x89PNG\r\n\x1a\n" + b"test-image"


def test_live_snapshot_attaches_documented_active_player_runes():
    service = GameService()
    payloads = {
        "activeplayer": {"riotIdGameName": "Local", "riotIdTagLine": "EUW", "championStats": {}},
        "playerlist": [{"riotIdGameName": "Local", "riotIdTagLine": "EUW", "team": "ORDER"}],
        "gamestats": {"gameMode": "CLASSIC", "gameTime": 30},
        "eventdata": {"Events": []},
        "activeplayerrunes": {"keystone": {"id": 8005, "displayName": "Press the Attack"}, "statRunes": [{"id": 5008}]},
    }
    calls = []
    service.request_data = lambda endpoint: (calls.append(endpoint), payloads[endpoint])[1]
    snapshot = service.get_live_snapshot()
    assert snapshot["local_player"]["runes"] == payloads["activeplayerrunes"]
    assert snapshot["all_players"][0]["runes"] == payloads["activeplayerrunes"]
    assert calls[-1] == "activeplayerrunes"
    payloads["gamestats"]["gameTime"] = 31
    service.get_live_snapshot()
    assert calls.count("activeplayerrunes") == 1  # fixed rune page is cached between telemetry ticks
    payloads["gamestats"]["gameTime"] = 0.2
    service.get_live_snapshot()
    assert calls.count("activeplayerrunes") == 2  # a new match cannot inherit the old page


def test_failed_rune_endpoint_is_backed_off_between_live_ticks():
    service = GameService()
    payloads = {
        "activeplayer": {"riotId": "Local#EUW"},
        "playerlist": [{"riotId": "Local#EUW", "team": "ORDER"}],
        "gamestats": {"gameMode": "CLASSIC", "gameTime": 30},
        "eventdata": {"Events": []},
    }
    calls = []

    def request(endpoint):
        calls.append(endpoint)
        if endpoint == "activeplayerrunes":
            raise requests.RequestException("fixture unavailable")
        return payloads[endpoint]

    service.request_data = request
    assert service.get_live_snapshot() is not None
    payloads["gamestats"]["gameTime"] = 32
    assert service.get_live_snapshot() is not None
    assert calls.count("activeplayerrunes") == 1


def test_live_asset_resolution_handles_rune_ids_shards_and_full_roster_items(tmp_path: Path):
    import backend.assets as assets
    downloaded_urls = []

    def download(url: str, path: Path):
        downloaded_urls.append(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
        return path

    with patch.object(assets, "_version", return_value="16.20.1"), \
            patch.object(assets, "_item_version", return_value="16.20.1"), \
            patch.object(assets, "get_storage_manager", return_value=SimpleNamespace(ddragon_dir=tmp_path)), \
            patch.object(assets, "_cached_or_download", side_effect=download):
        rune_map = assets._rune_icons_by_id("16.20.1")
        assert rune_map["8005"].endswith("PressTheAttack/PressTheAttack.png")
        assert rune_map["9111"].endswith("Triumph.png")
        assert rune_map["9104"].endswith("LegendAlacrity.png")
        assert rune_map[assets._asset_label_key("Legend: Alacrity")].endswith("LegendAlacrity.png")
        assert assets._resolve_rune_image("9104", rune_map, "16.20.1", tmp_path)
        shard = assets._resolve_rune_image("5008", rune_map, "16.20.1", tmp_path)
        assert shard and "data:image/png;base64," in shard
        ids = ["3158", "3010", "3801"] + [str(1000 + index) for index in range(60)]
        result = assets.resolve_meta_assets([], ids, [], [])
    assert all(result.get(f"item:{item_id}") for item_id in ids)
    assert all(any(url.endswith(f"/img/item/{item_id}.png") for url in downloaded_urls)
               for item_id in ("3158", "3010", "3801"))


def test_draft_requests_tree_minor_runes_and_shards_from_shared_resolver():
    draft = DraftRuntime.__new__(DraftRuntime)
    draft.catalog = []
    pages = [{"primary_tree_id": 8000, "secondary_tree_id": 8100,
              "keystone_id": 8005, "slot_ids": [9101, 9104],
              "secondary_slot_ids": [8126], "shard_ids": [5008, 5008, 5013]}]
    captured = {}
    with patch("backend.draft.resolve_meta_assets", side_effect=lambda *args, **kwargs: (captured.update(kwargs) or {})):
        draft._rune_assets(pages, [], {})
    assert captured["runes"] == ["8000", "8100", "8005", "9101", "9104", "8126", "5008", "5013"]


def test_legend_haste_uses_current_patch_metadata_and_path_scoped_cache(tmp_path: Path):
    import backend.assets as assets
    downloads = []

    def download(url: str, path: Path):
        downloads.append((url, path))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
        return path

    with patch.object(assets, "_cached_or_download", side_effect=download):
        icons = assets._rune_icons_by_id("16.20.1")
        assert icons["9105"] == "perk-images/Styles/Precision/LegendHaste/LegendHaste.png"
        # The previous cache keyed only by ID must not be consulted.
        stale = tmp_path / "runes" / "16.20.1" / "9105.png"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"old-tenacity-icon")
        image = assets._resolve_rune_image("9105", icons, "16.20.1", tmp_path)
    assert image and image.startswith("data:image/png;base64,")
    assert len(downloads) == 1
    assert downloads[0][0].endswith("/perk-images/Styles/Precision/LegendHaste/LegendHaste.png")
    assert downloads[0][1].name.startswith("LegendHaste-")


def test_ambessa_mid_build_has_legal_champion_starters_and_lcu_payload_block():
    from app.services.draft_analyzer_service import DraftAnalyzerService
    from app.services.lcu_service import LCUService

    analyzer = DraftAnalyzerService()
    build = analyzer.get_champion_build("Ambessa", [], "mid")
    assert [item["id"] for item in build["starter_items"]] == ["1055", "2003"]
    assert sum(analyzer.items[item["id"]]["gold"]["total"] for item in build["starter_items"]) <= 500

    captured = {}
    session = SimpleNamespace(
        get=lambda url, **kwargs: SimpleNamespace(status_code=200, json=lambda: ({"summonerId": 17} if "current-summoner" in url else {"itemSets": [{"uid": "user-set", "title": "Keep me"}]})),
        put=lambda url, **kwargs: (captured.update(kwargs) or SimpleNamespace(status_code=204)),
    )
    service = LCUService.__new__(LCUService)
    service.session = session
    service.port = 2999
    service.is_connected = lambda: True
    ok, _ = service.import_item_set(200, "Ambessa", "mid", ["3071"], starter_ids=[item["id"] for item in build["starter_items"]], situational=[{"label": "Corta curas", "items": [{"id": "6600"}]}])
    assert ok
    payload = captured["json"]
    item_set = next(entry for entry in payload["itemSets"] if entry["uid"].startswith(service.ITEM_SET_UID_PREFIX))
    blocks = item_set["blocks"]
    assert [block["type"] for block in blocks] == ["Objetos iniciales", "Objetos principales (1)", "Corta curas"]
    assert [item["id"] for item in blocks[0]["items"]] == ["1055", "2003"]
    assert all(isinstance(item["id"], str) for block in blocks for item in block["items"])
    assert any(entry["uid"] == "user-set" for entry in payload["itemSets"])


def test_draft_import_selection_forwards_curated_starters_to_lcu():
    runtime = DraftRuntime.__new__(DraftRuntime)
    runtime._canonical = lambda name: name if name == "Ambessa" else None
    runtime.repository = SimpleNamespace(consultar=lambda *args: SimpleNamespace(
        estado=SimpleNamespace(value="AVAILABLE"), datos={"runes": []}))
    runtime.analyzer = SimpleNamespace(
        get_champion_profile=lambda _champion: {"summoner_spells": ["Destello", "Ignición"]},
        get_champion_build=lambda *_args: {"champion_id": 200, "items": [{"id": "3071", "name": "Cuchilla negra"}],
            "boots": None, "starter_items": [{"id": "1055", "name": "Espada de Doran"}, {"id": "2003", "name": "Poción de vida"}], "situational": []},
        get_situational_items=lambda _champion: [],
        normalizar_hechizos=staticmethod(lambda _spells, _role: ("Destello", "Ignición")),
        item_names={})
    runtime._item_catalog = {item_id: {"name": name, "maps": {"11": True}}
        for item_id, name in (("3071", "Cuchilla negra"), ("1055", "Espada de Doran"), ("2003", "Poción de vida"))}
    calls = {}
    runtime.lcu = SimpleNamespace(
        import_item_set=lambda *args, **kwargs: (calls.update({"args": args, "kwargs": kwargs}) or (True, "ok")),
        import_summoner_spells=lambda *_args: (True, "ok"))
    result = runtime.import_selection({"kind": "build", "champion": "Ambessa", "role": "mid", "pageIndex": 0})
    assert result["ok"] is True
    assert calls["kwargs"]["starter_ids"] == ["1055", "2003"]


def test_live_tower_kill_actor_and_timestamps_are_normalized_safely():
    from app.services.live_event_normalizer import normalize_live_event

    tower = normalize_live_event({"EventName": "ChampionKill", "EventID": 9, "EventTime": 92.5,
                                  "KillerName": "Turret_T1_R_03_A", "VictimName": "Ambessa"},
                                 victim_champion="Ambessa")
    assert tower["KillerActorType"] == "tower"
    assert tower["VictimActorType"] == "champion"
    assert tower["EventDescription"] == "Ambessa murió por una torre"
    assert tower["EventTime"] == 92.5
    missing = normalize_live_event({"EventName": "ChampionKill", "EventTime": -1, "VictimName": "Ambessa"}, victim_champion="Ambessa")
    assert missing["KillerActorType"] == "unknown"
    assert missing["EventTime"] is None
    assert missing["EventDescription"] == "Ambessa murió por una causa no identificada"
    destroyed = normalize_live_event({"EventName": "TurretKilled", "EventTime": 100, "TurretKilled": "Turret_T1_L_03"}, killer_champion="Ambessa")
    assert destroyed["ObjectiveKind"] == "tower"
    assert destroyed["ObjectiveLabel"].startswith("Torre de")


def test_postgame_tower_death_keeps_tower_to_champion_actor_relationship():
    from backend.live_match import LiveMatchRuntime

    runtime = LiveMatchRuntime.__new__(LiveMatchRuntime)
    runtime.items = {}
    payload = runtime._post_game_payload({
        "session_id": "fixture", "players": {"victim": {"champion_name": "Ambessa", "team": "CHAOS", "is_local_player": True}},
        "final_scoreboard": {}, "local_team": "CHAOS", "game_mode": "CLASSIC", "duration": 900,
        "events": [{"type": "death_exact", "event_id": "tower-death", "time": 125.75,
                    "victim_key": "victim", "killer_actor_type": "tower", "killer_actor_name": "torre",
                    "victim_actor_type": "champion", "victim_actor_name": "Ambessa"}],
    })
    event = payload["events"][0]
    assert event["EventName"] == "ChampionKill"
    assert event["KillerActorType"] == "tower"
    assert event["VictimActorType"] == "champion"
    assert event["EventDescription"] == "Ambessa murió por una torre"
    assert event["EventTime"] == 125.75


def test_draft_item_set_starter_fallback_varies_by_role():
    from app.services.lcu_service import LCUService
    service = LCUService.__new__(LCUService)
    captured = []
    service.session = SimpleNamespace(
        get=lambda url, **kwargs: SimpleNamespace(status_code=200, json=lambda: {"summonerId": 17} if "current-summoner" in url else {"itemSets": []}),
        put=lambda url, **kwargs: (captured.append(kwargs["json"]) or SimpleNamespace(status_code=204)),
    )
    service.port = 2999
    service.is_connected = lambda: True
    for role in ("support", "jungle"):
        assert service.import_item_set(200, "Test", role, ["3071"])[0]
    supports = next(s for s in captured[0]["itemSets"] if s["uid"].startswith(service.ITEM_SET_UID_PREFIX))["blocks"]
    jungle = next(s for s in captured[1]["itemSets"] if s["uid"].startswith(service.ITEM_SET_UID_PREFIX))["blocks"]
    assert supports[0]["type"] == jungle[0]["type"] == "Objetos iniciales"
    assert [item["id"] for item in supports[0]["items"]] == ["3865", "2003"]
    assert sum(item["id"] in service.JUNGLE_STARTER_IDS for item in jungle[0]["items"]) == 1


def test_active_recording_snapshot_includes_live_metadata_and_size(tmp_path: Path):
    video = tmp_path / "active.mp4"
    video.write_bytes(b"recording bytes")
    runtime = RecordingRuntime.__new__(RecordingRuntime)
    runtime.lock = threading.RLock()
    runtime.started_at = datetime.now(UTC)
    runtime.output_path = video
    runtime.process = object()
    runtime.state = "recording"
    runtime.message = "Recording"
    runtime.last_error = ""
    runtime.active_session_id = None
    runtime.live_metadata = {}
    runtime.game_monitor_index = 0
    runtime.associate_live_session("session-1", {"champion": "Briar", "gameMode": "CLASSIC", "role": "JUNGLE"})
    status = runtime.snapshot()
    assert status["recordingName"] == "active.mp4"
    assert status["fileSizeBytes"] == len(b"recording bytes")
    assert status["currentChampion"] == "Briar"
    assert status["currentGameMode"] == "CLASSIC"
    assert status["currentRole"] == "JUNGLE"


def test_active_recording_is_not_listed_as_incomplete_or_deletable(tmp_path: Path):
    video = tmp_path / "active.mp4"
    video.write_bytes(b"recording bytes")
    app = Application.__new__(Application)
    app.settings = SimpleNamespace(load=lambda: {"recording_output_dir": str(tmp_path)})
    app._recordings = SimpleNamespace(snapshot=lambda: {
        "recordingName": "active.mp4", "state": "recording", "elapsedSeconds": 17,
        "fileSizeBytes": video.stat().st_size, "currentChampion": "Briar",
        "currentGameMode": "CLASSIC", "currentRole": "JUNGLE",
    })
    app._recording_history_tracker = SimpleNamespace(load_saved_sessions=lambda: [])
    app._catalog = [{"id": "Briar", "name": "Briar", "key": "233"}]
    row = app._dispatch_active("recordings.list")[0]
    assert row["active"] is True
    assert row["complete"] is False
    assert row["champion"] == "Briar"
    assert row["game_mode"] == "CLASSIC"
    assert row["position"] == "JUNGLE"
    assert row["duration"] == 17
    try:
        app._dispatch_active("recordings.delete", {"name": "active.mp4"})
    except ValueError as error:
        assert "activa" in str(error)
    else:
        raise AssertionError("active recording must be protected from deletion")
    assert video.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex and byte-lock semantics")
def test_recording_delete_cleans_owned_sidecar_lock_and_auxiliary_files(tmp_path: Path):
    library = RecordingLibrary(tmp_path)
    video = tmp_path / "match.mp4"
    video.write_bytes(b"video")
    assert library.write_metadata(video, {"complete": True, "session_id": "one"})
    sidecar = library.metadata_path(video)
    legacy_lock = sidecar.with_name(f".{sidecar.name}.lock")
    legacy_lock.write_bytes(b"\0")
    seek_cache = tmp_path / ".seek_cache" / "match.mp4.123.456.seek.mp4"
    seek_cache.parent.mkdir()
    seek_cache.write_bytes(b"proxy")

    other = tmp_path / "other.mp4"
    other.write_bytes(b"other video")
    library.write_metadata(other, {"complete": True, "session_id": "two"})
    unrelated_lock = tmp_path / ".unrelated.lock"
    unrelated_lock.write_bytes(b"keep")

    assert library.delete(video) is True
    assert not video.exists() and not sidecar.exists() and not legacy_lock.exists()
    assert not seek_cache.exists()
    assert other.exists() and library.metadata_path(other).exists()
    assert unrelated_lock.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex and byte-lock semantics")
def test_recording_delete_preserves_an_actively_owned_legacy_lock(tmp_path: Path):
    import msvcrt

    library = RecordingLibrary(tmp_path)
    video = tmp_path / "active.mp4"
    video.write_bytes(b"video")
    library.write_metadata(video, {"complete": True})
    sidecar = library.metadata_path(video)
    legacy_lock = sidecar.with_name(f".{sidecar.name}.lock")
    legacy_lock.write_bytes(b"\0")
    handle = legacy_lock.open("r+b")
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    try:
        assert library.delete(video) is False
        assert video.exists() and sidecar.exists() and legacy_lock.exists()
    finally:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        handle.close()
    assert library.delete(video) is True
    assert not video.exists() and not sidecar.exists() and not legacy_lock.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows named mutex semantics")
def test_windows_atomic_recording_metadata_does_not_leave_lock_files(tmp_path: Path):
    library = RecordingLibrary(tmp_path)
    video = tmp_path / "written.mp4"
    video.write_bytes(b"video")
    assert library.write_metadata(video, {"champion": "Ambessa"})
    assert library.load_metadata(video) == {"champion": "Ambessa"}
    assert not (tmp_path / ".written.json.lock").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows byte-lock semantics")
def test_recording_list_recovers_only_released_recording_lock_artifacts(tmp_path: Path):
    library = RecordingLibrary(tmp_path)
    video = tmp_path / "match.mp4"
    video.write_bytes(b"video")
    library.write_metadata(video, {"complete": True})
    orphan = tmp_path / ".match.json.lock"
    orphan.write_bytes(b"\0")
    unrelated = tmp_path / ".other.json.lock"
    unrelated.write_bytes(b"\0")
    # The maintenance pass is limited to names belonging to recordings in the
    # configured directory and probes lock ownership before removing a path.
    library.list_recordings()
    assert not orphan.exists()
    assert unrelated.exists()
