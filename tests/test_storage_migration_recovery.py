from __future__ import annotations

import json
from pathlib import Path

from app.services import storage_manager as storage_module
from app.services.storage_manager import StorageManager


def test_restart_marks_uncommitted_journal_recoverable_without_switching_root(
    tmp_path: Path, monkeypatch
) -> None:
    pointer = tmp_path / "bootstrap" / "storage.json"
    monkeypatch.setattr(storage_module, "bootstrap_config_path", lambda: pointer)
    old_root = tmp_path / "old-root"
    destination = tmp_path / "new-root"
    old_root.mkdir()
    destination.mkdir()
    (old_root / "match_history_cache.json").write_text('{"count":168}', encoding="utf-8")
    (destination / ".solralol-storage.json").write_text('{"schema":1}', encoding="utf-8")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"data_root": str(old_root)}), encoding="utf-8")
    journal = storage_module.bootstrap_config_path().with_name("migration.json")
    journal.write_text(json.dumps({
        "migrationId": "interrupted-1", "state": "copying", "phase": "copying",
        "source": str(old_root), "destination": str(destination), "stage": str(destination.parent / ".partial-stage"),
    }), encoding="utf-8")

    recovered = StorageManager.startup_migration_state()

    assert recovered and recovered["state"] == "recovery_required"
    assert json.loads(pointer.read_text(encoding="utf-8"))["data_root"] == str(old_root)
    assert destination.exists()


def test_restart_recognizes_commit_if_pointer_was_switched_before_shutdown(
    tmp_path: Path, monkeypatch
) -> None:
    pointer = tmp_path / "bootstrap" / "storage.json"
    monkeypatch.setattr(storage_module, "bootstrap_config_path", lambda: pointer)
    destination = tmp_path / "new-root"
    destination.mkdir()
    (destination / ".solralol-storage.json").write_text('{"schema":1}', encoding="utf-8")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"data_root": str(destination)}), encoding="utf-8")
    journal = pointer.with_name("migration.json")
    journal.write_text(json.dumps({"migrationId": "committing-1", "state": "committing",
                                   "destination": str(destination)}), encoding="utf-8")

    recovered = StorageManager.startup_migration_state()

    assert recovered and recovered["state"] == "complete"
    assert json.loads(journal.read_text(encoding="utf-8"))["phase"] == "complete"


def test_failed_bootstrap_commit_keeps_original_root_and_verified_stage(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(storage_module.tempfile, "gettempdir", lambda: str(tmp_path / "unrelated-temp"))
    pointer = tmp_path / "bootstrap" / "storage.json"
    monkeypatch.setattr(storage_module, "bootstrap_config_path", lambda: pointer)
    source = tmp_path / "old-root"
    destination = tmp_path / "new-root"
    source.mkdir()
    (source / "match_history_cache.json").write_text('{"count":168}', encoding="utf-8")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"data_root": str(source)}), encoding="utf-8")
    manager = StorageManager(source)
    monkeypatch.setattr(manager, "_write_bootstrap_root", lambda _root: (_ for _ in ()).throw(PermissionError("locked pointer")))

    try:
        manager.migrate(destination, migration_id="commit-failure")
    except PermissionError:
        pass
    else:
        raise AssertionError("expected bootstrap commit failure")

    assert json.loads(pointer.read_text(encoding="utf-8"))["data_root"] == str(source)
    assert json.loads((source / "match_history_cache.json").read_text(encoding="utf-8"))["count"] == 168
    assert (destination.parent / ".new-root.rollback-commit-failure" / "match_history_cache.json").is_file()


def test_retry_replaces_only_a_marked_incomplete_destination_and_keeps_backup(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(storage_module.tempfile, "gettempdir", lambda: str(tmp_path / "unrelated-temp"))
    pointer = tmp_path / "bootstrap" / "storage.json"
    monkeypatch.setattr(storage_module, "bootstrap_config_path", lambda: pointer)
    source = tmp_path / "old-root"
    destination = tmp_path / "new-root"
    source.mkdir()
    destination.mkdir()
    (source / "match_history_cache.json").write_text('{"count":168}', encoding="utf-8")
    (destination / ".solralol-storage.json").write_text('{"schema":1}', encoding="utf-8")
    (destination / "partial-copy.json").write_text('{"incomplete":true}', encoding="utf-8")
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text(json.dumps({"data_root": str(source)}), encoding="utf-8")

    result = StorageManager(source).migrate(destination, migration_id="retry-1")

    assert json.loads((destination / "match_history_cache.json").read_text(encoding="utf-8"))["count"] == 168
    assert (source / "match_history_cache.json").is_file()
    backup = Path(result["previousDestinationBackup"])
    assert (backup / "partial-copy.json").is_file()
