from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import storage_manager as storage_module
from app.services.storage_manager import StorageManager


@pytest.mark.slow
def test_migrates_over_one_gigabyte_with_thousands_of_files_and_streamed_progress(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(storage_module.tempfile, "gettempdir", lambda: str(tmp_path / "unrelated-temp"))
    pointer = tmp_path / "bootstrap" / "storage.json"
    monkeypatch.setattr(storage_module, "bootstrap_config_path", lambda: pointer)
    source = tmp_path / "old-root"
    destination = tmp_path / "new-root"
    small_files = source / "cache" / "many"
    small_files.mkdir(parents=True)
    video = source / "recordings" / "videos" / "large.mp4"
    video.parent.mkdir(parents=True)
    with video.open("wb") as stream:
        stream.truncate(1024**3 + 64 * 1024**2)
    for index in range(3000):
        (small_files / f"cache-{index:04}.json").write_text('{"ok":true}', encoding="utf-8")

    manager = StorageManager(source)
    updates: list[dict[str, object]] = []
    result = manager.migrate(destination, progress=updates.append, migration_id="large-fixture")

    assert result["migratedBytes"] > 1024**3
    assert result["fileCount"] >= 3001
    assert (destination / "recordings" / "videos" / "large.mp4").stat().st_size == video.stat().st_size
    assert (destination / "cache" / "many" / "cache-2999.json").read_bytes() == b'{"ok":true}'
    assert source.exists()
    copy_updates = [item for item in updates if item.get("state") == "copying"]
    assert any(0 < int(item.get("currentBytes") or 0) < int(item.get("totalBytes") or 0) for item in copy_updates)
    assert updates[-1]["state"] == "complete"
    assert json.loads(pointer.read_text(encoding="utf-8"))["data_root"] == str(destination.resolve())
