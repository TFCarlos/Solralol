"""Execution-path regressions; League/LCU responses here are simulated."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from app.services.recording_service import RecordingLibrary
from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.lcu_service import LCUService
from app.services import storage_manager as storage
from backend.draft import DraftRuntime


@pytest.mark.skipif(os.name != "nt", reason="Windows handle sharing and kernel mutexes")
@pytest.mark.parametrize("byte_locked", [True, False])
def test_recovery_preserves_legacy_owner_and_open_waiter_until_process_exits(tmp_path, byte_locked):
    target = tmp_path / "Partida - 2026-10-24_15-36.json"
    lock = tmp_path / f".{target.name}.lock"
    lock.write_bytes(b"\0")
    script = """
import msvcrt, pathlib, sys
handle = pathlib.Path(sys.argv[1]).open('r+b')
if sys.argv[2] == 'True': msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
print('ready', flush=True)
sys.stdin.readline()
"""
    process = subprocess.Popen([sys.executable, "-u", "-c", script, str(lock), str(byte_locked)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert process.stdout.readline().strip() == "ready"
        library = RecordingLibrary(tmp_path)
        assert library.cleanup_legacy_lock_artifacts() == 0
        assert lock.exists()
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
    # Recovery covers orphan locks whose video and JSON were already deleted.
    assert library.cleanup_legacy_lock_artifacts() == 1
    assert not lock.exists()
    unrelated = tmp_path / ".unrelated.json.lock"
    unrelated.write_bytes(b"\0")
    unrelated.with_name("unrelated.json").write_text('{"complete":true}')
    library.cleanup_legacy_lock_artifacts()
    assert unrelated.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows abandoned mutex recovery")
def test_crashed_atomic_metadata_writer_preserves_json_and_releases_mutex(tmp_path):
    video = tmp_path / "custom.mp4"
    video.write_bytes(b"video")
    target = video.with_suffix(".json")
    storage.atomic_write_json(target, {"complete": True, "revision": 1})
    script = """
import sys
from app.services import storage_manager as storage
def pause(*args):
    print('ready', flush=True)
    sys.stdin.readline()
storage._retry_replace = pause
storage.atomic_write_json(sys.argv[1], {'complete': False, 'revision': 2})
"""
    process = subprocess.Popen([sys.executable, "-u", "-c", script, str(target)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        assert process.stdout.readline().strip() == "ready"
        with pytest.raises(TimeoutError):
            storage.atomic_write_bytes(target, b"{}", timeout=0.02)
        assert json.loads(target.read_text()) == {"complete": True, "revision": 1}
    finally:
        process.terminate()
        process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
    storage.atomic_write_json(target, {"complete": True, "revision": 3})
    assert json.loads(target.read_text())["revision"] == 3
    assert not (tmp_path / ".custom.json.lock").exists()
    assert RecordingLibrary(tmp_path).delete(video)
    assert not list(tmp_path.glob(".custom.json.*.tmp"))


def test_failed_video_deletion_keeps_recording_metadata(tmp_path, monkeypatch):
    video = tmp_path / "in-use.mp4"
    video.write_bytes(b"video")
    library = RecordingLibrary(tmp_path)
    library.write_metadata(video, {"complete": True})
    original = library._unlink_with_retry
    monkeypatch.setattr(library, "_unlink_with_retry", lambda path: False if path == video else original(path))
    assert library.delete(video) is False
    assert video.exists() and library.metadata_path(video).exists()


def test_rune_id_reuse_and_shared_cache_follow_patch_metadata(tmp_path, monkeypatch):
    import data_dragon
    import backend.assets as assets

    catalog_dir = tmp_path / "catalog"
    catalog_dir.mkdir()
    cache = tmp_path / "cache"
    monkeypatch.setattr(data_dragon, "DATA_DIR", catalog_dir)
    monkeypatch.setattr(data_dragon, "RUNE_ICON_CATALOG_CACHE", {})
    monkeypatch.setattr(data_dragon, "_RUNE_ICON_CATALOG_STAMPS", {})
    monkeypatch.setattr(data_dragon, "RUNE_ICON_CATALOG_FAILED", set())
    monkeypatch.setattr(storage, "get_storage_manager", lambda: SimpleNamespace(ddragon_dir=cache))
    old_icon = "perk-images/Styles/Precision/LegendTenacity/LegendTenacity.png"
    new_icon = "perk-images/Styles/Precision/LegendHaste/LegendHaste.png"

    def write(version, key, icon):
        rows = [{"id": 8000, "key": "Precision", "name": "Precision", "icon": "perk-images/Styles/7201_Precision.png",
                 "slots": [{"runes": [{"id": 9105, "key": key, "name": key, "icon": icon},
                                       {"id": 9111, "key": "Triumph", "name": "Triumph", "icon": "perk-images/Styles/Precision/Triumph.png"}]}]}]
        (catalog_dir / f"runes_reforged_{version}.json").write_text(json.dumps(rows), encoding="utf-8")

    write("14.9.1", "LegendTenacity", old_icon)
    write("16.20.1", "LegendHaste", new_icon)
    assert assets._rune_icons_by_id("14.9.1")["9105"] == old_icon
    assert assets._rune_icons_by_id("16.20.1")["9105"] == new_icon
    assert assets._rune_icons_by_id("16.20.1")["9111"].endswith("Triumph.png")
    stale = cache / "runes" / "16.20.1" / "9105.png"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old cached tenacity")
    assert data_dragon.get_rune_icon_path("9105", "16.20.1", download=False) is None
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==")
    calls = []
    monkeypatch.setattr(data_dragon.requests, "get", lambda url, **kwargs: (calls.append(url) or SimpleNamespace(content=png, raise_for_status=lambda: None)))
    path = data_dragon.get_rune_icon_path("LegendHaste", "16.20.1")
    assert path == data_dragon.rune_icon_cache_path("16.20.1", new_icon, cache)
    assert assets._resolve_rune_image("9105", assets._rune_icons_by_id("16.20.1"), "16.20.1", cache)
    assert calls == [f"https://ddragon.leagueoflegends.com/cdn/img/{new_icon}"]
    assert data_dragon.get_rune_icon_path("Legend: Tenacity", "16.20.1") is None
    # A catalog replacement in the same process invalidates cached metadata.
    write("16.20.1", "NewDefinition", new_icon.replace("LegendHaste", "NewDefinition"))
    assert "NewDefinition" in assets._rune_icons_by_id("16.20.1")["9105"]


@pytest.fixture(scope="module")
def analyzer():
    return DraftAnalyzerService()


@pytest.mark.parametrize("champion,role,primary", [
    ("Ambessa", "mid", "1055"), ("Ahri", "mid", "1056"),
    ("Briar", "jungle", "1103"), ("Seraphine", "support", "3865"),
])
def test_curated_starters_are_legal_affordable_and_role_appropriate(analyzer, champion, role, primary):
    entries = analyzer.get_starter_items(champion, role)
    assert entries[0]["id"] == primary
    assert sum(analyzer.items[e["id"]]["gold"]["total"] * e["count"] for e in entries) <= 500
    assert all(analyzer.curador.catalogo.validar_objeto_inicial(e["id"], champion).elegible for e in entries)
    if champion == "Ahri":
        assert next(e for e in entries if e["id"] == "2003")["count"] == 2


def test_starter_fallback_uses_resource_profile_and_discards_wrong_role_items(analyzer):
    manaless = {"basic_info": {"damage_type": "AP", "resource_type": "Energy"}}
    assert analyzer.get_starter_items("Akali", "mid", profile=manaless, variant={})[0]["id"] == "1054"
    ad = {"basic_info": {"damage_type": "AD", "resource_type": "Energy"}}
    entries = analyzer.get_starter_items("Ambessa", "mid", profile=ad, variant={"starter_item_ids": [1101, 1102, 3865]})
    assert [e["id"] for e in entries] == ["1055"]


def test_selected_rune_page_starters_take_precedence_over_profile(analyzer):
    runtime = DraftRuntime.__new__(DraftRuntime)
    runtime.analyzer, runtime._item_catalog = analyzer, analyzer.items
    page = {"starter_item_entries": [{"item_id": 1054, "quantity": 1}, {"item_id": 2003, "quantity": 1}]}
    base = analyzer.get_champion_build("Ahri", [], "mid")
    build = runtime._build_for_page("Ahri", page, [], "mid", base)
    assert [(e["id"], e["count"]) for e in build["starter_items"]] == [("1054", 1), ("2003", 1)]


@pytest.mark.parametrize("unit,kind,cause", [
    ("Turret_T2_L_03_A", "tower", "una torre"),
    ("Minion_T200_Melee_01", "minion", "súbditos"),
])
def test_nonchampion_unit_overrides_stale_roster_identity(unit, kind, cause):
    from app.services.live_event_normalizer import normalize_live_event
    event = normalize_live_event({"EventName": "ChampionKill", "EventID": 221, "EventTime": 754.2,
                                  "KillerName": unit, "VictimName": "fixture-player", "Assisters": [],
                                  "KillerChampion": "Briar"}, killer_champion="Briar", victim_champion="Briar")
    assert event["KillerActorType"] == kind
    assert "KillerChampion" not in event
    assert event["VictimChampion"] == "Briar"
    assert event["EventDescription"] == f"Briar murió por {cause}"
    assert event["EventTime"] == 754.2


class _ItemSetClient:
    def __init__(self):
        self.payload = {"accountId": 17, "itemSets": [{"uid": "user-set", "title": "Mi conjunto"}], "timestamp": 0}

    def get(self, url, **_kwargs):
        value = {"summonerId": 17} if "current-summoner" in url else self.payload
        return SimpleNamespace(status_code=200, json=lambda: json.loads(json.dumps(value)))

    def put(self, _url, **kwargs):
        self.payload = json.loads(json.dumps(kwargs["json"], ensure_ascii=False))
        return SimpleNamespace(status_code=204)


def test_draft_to_serialized_lcu_payload_preserves_starter_counts_and_reimports(analyzer):
    client = _ItemSetClient()
    lcu = LCUService.__new__(LCUService)
    lcu.session, lcu.port, lcu._starter_analyzer = client, 2999, analyzer
    lcu.is_connected = lambda: True
    runtime = DraftRuntime.__new__(DraftRuntime)
    runtime.analyzer, runtime._item_catalog, runtime.lcu = analyzer, analyzer.items, lcu
    runtime._canonical = lambda name: name if name == "Ahri" else None
    runtime.repository = SimpleNamespace(consultar=lambda *_args: SimpleNamespace(estado=SimpleNamespace(value="AVAILABLE"), datos={"runes": []}))
    for _ in range(2):
        result = runtime.import_selection({"kind": "build", "champion": "Ahri", "role": "mid", "pageIndex": 0})
        assert result["ok"], result
    sets = client.get("/sets").json()["itemSets"]
    assert len(sets) == 2 and sets[0]["uid"] == "user-set"
    blocks = sets[1]["blocks"]
    assert blocks[0] == {"type": "Objetos iniciales", "items": [{"id": "1056", "count": 1}, {"id": "2003", "count": 2}]}
    assert blocks[1]["type"].startswith("Objetos principales")
    assert [b["type"] for b in blocks[2:]] == ["Botas recomendadas contra este equipo", "Corta curas", "Tanque / Resistencias", "Asesino / Daño explosivo", "Utilidad y Defensa"]
    for ids in (["999999"], ["1055", "1054"], ["1101"], ["3865"]):
        assert lcu.import_item_set(103, "Ahri", "mid", ["3100"], starter_ids=ids)[0] is False
