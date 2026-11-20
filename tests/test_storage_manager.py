from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

from app.services import storage_manager as storage_module
from app.services.storage_manager import StorageManager, atomic_update_json, atomic_write_json


def _write_process_cache_entry(args: tuple[str, int]) -> None:
    target, worker = args
    atomic_update_json(target, lambda current: {**current, str(worker): worker}, default={})


def test_atomic_json_writes_serialize_concurrent_updates(tmp_path: Path) -> None:
    target = tmp_path / "history.json"

    def write(worker: int) -> None:
        for index in range(12):
            atomic_write_json(target, {"worker": worker, "index": index, "rows": list(range(300))})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(8)))

    result = json.loads(target.read_text(encoding="utf-8"))
    assert 0 <= result["worker"] < 8
    assert 0 <= result["index"] < 12
    assert result["rows"] == list(range(300))
    assert not list(tmp_path.glob(".history.json.*.tmp"))


def test_json_updates_are_serialized_across_backend_processes(tmp_path: Path) -> None:
    target = str(tmp_path / "shared.json")
    with ProcessPoolExecutor(max_workers=4) as executor:
        list(executor.map(_write_process_cache_entry, [(target, worker) for worker in range(12)]))
    value = json.loads(Path(target).read_text(encoding="utf-8"))
    assert value == {str(worker): worker for worker in range(12)}


def test_failed_replace_preserves_previous_valid_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "history.json"
    target.write_text('{"matches": 168}\n', encoding="utf-8")

    def fail_replace(_source: Path, _target: Path) -> None:
        raise PermissionError(5, "Access is denied")

    monkeypatch.setattr(storage_module, "_retry_replace", fail_replace)
    with pytest.raises(PermissionError):
        atomic_write_json(target, {"matches": 169})
    assert json.loads(target.read_text(encoding="utf-8")) == {"matches": 168}
    assert not list(tmp_path.glob(".history.json.*.tmp"))


def test_storage_statistics_count_central_categories_once(tmp_path: Path) -> None:
    root = tmp_path / "data-root"
    (root / "recordings" / "videos").mkdir(parents=True)
    (root / "profiles" / "account").mkdir(parents=True)
    (root / "recordings" / "videos" / "clip.mp4").write_bytes(b"1234567")
    (root / "profiles" / "account" / "match_history.json").write_bytes(b"123")
    (root / "settings.json").write_bytes(b"12345")

    result = StorageManager(root).storage_stats()

    assert result["totalBytes"] == 15
    assert result["categories"] == {"recordings": 7, "matches": 3, "analysis": 0, "cache": 0, "other": 5}


def test_storage_migration_verifies_copy_and_keeps_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage_module.tempfile, "gettempdir", lambda: str(tmp_path / "unrelated-temp"))
    pointer = tmp_path / "bootstrap" / "storage.json"
    monkeypatch.setattr(storage_module, "bootstrap_config_path", lambda: pointer)
    source = tmp_path / "old-root"
    source.mkdir()
    (source / "match_history_cache.json").write_text(json.dumps({"matches": 168}), encoding="utf-8")
    (source / "recordings").mkdir()
    (source / "recordings" / "sample.mp4").write_bytes(b"video-data")
    electron_data = tmp_path / "old-electron-user-data"
    (electron_data / "Local Storage").mkdir(parents=True)
    (electron_data / "Local Storage" / "layout.leveldb").write_bytes(b"layout")
    (electron_data / "storage.json").write_text('{"data_root":"old"}', encoding="utf-8")
    monkeypatch.setenv("SOLRALOL_LEGACY_ELECTRON_DATA", str(electron_data))
    destination = tmp_path / "new-root"
    manager = StorageManager(source)

    plan = manager.migration_plan(destination)
    updates: list[dict[str, object]] = []
    result = manager.migrate(destination, progress=updates.append)

    assert result["root"] == str(destination.resolve())
    assert (destination / "match_history_cache.json").read_bytes() == (source / "match_history_cache.json").read_bytes()
    assert (destination / "recordings" / "sample.mp4").read_bytes() == b"video-data"
    assert source.exists()
    assert json.loads(pointer.read_text(encoding="utf-8"))["data_root"] == str(destination.resolve())
    assert plan.file_count == 3
    assert (destination / "electron" / "Local Storage" / "layout.leveldb").read_bytes() == b"layout"
    assert not (destination / "electron" / "storage.json").exists()
    assert updates[-1]["state"] == "complete"


def test_restoring_default_merges_data_and_keeps_previous_target_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(storage_module.tempfile, "gettempdir", lambda: str(tmp_path / "unrelated-temp"))
    pointer = tmp_path / "bootstrap" / "storage.json"
    monkeypatch.setattr(storage_module, "bootstrap_config_path", lambda: pointer)
    source = tmp_path / "custom-root"
    destination = tmp_path / "default-root"
    source.mkdir(); destination.mkdir()
    (source / "settings.json").write_text('{"new": true}', encoding="utf-8")
    (destination / "settings.json").write_text('{"old": true}', encoding="utf-8")
    (destination / "older-history.json").write_text('{"matches": 168}', encoding="utf-8")
    monkeypatch.setattr(StorageManager, "default_root", property(lambda _self: destination.resolve()))
    manager = StorageManager(source)

    result = manager.migrate(destination)

    migrated_settings = json.loads((destination / "settings.json").read_text(encoding="utf-8"))
    assert migrated_settings["new"] is True
    assert migrated_settings["recording_output_dir"] == str(destination / "recordings" / "videos")
    assert json.loads((destination / "older-history.json").read_text(encoding="utf-8")) == {"matches": 168}
    backup = Path(result["previousDestinationBackup"])
    assert json.loads((backup / "settings.json").read_text(encoding="utf-8")) == {"old": True}
