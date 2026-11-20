from __future__ import annotations

import sys
from pathlib import Path

import _paths


def test_packaged_data_sync_runs_once_per_bundle_version(tmp_path: Path, monkeypatch) -> None:
    bundle = tmp_path / "bundle" / "data"
    (bundle / "champion_metadata").mkdir(parents=True)
    asset = bundle / "champion_metadata" / "Ahri.json"
    asset.write_text('{"name":"Ahri"}', encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "profile")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delenv("SOLRALOL_DATA_DIR", raising=False)
    monkeypatch.setenv("SOLRALOL_BUNDLE_DATA_DIR", str(bundle))
    monkeypatch.setenv("SOLRALOL_BUNDLE_VERSION", "0.1.0")

    resolved = _paths._resolve_data_dir()
    local_asset = resolved / "champion_metadata" / "Ahri.json"
    assert resolved == tmp_path / "profile" / ".solralol" / "data"
    assert local_asset.read_text(encoding="utf-8") == '{"name":"Ahri"}'
    assert (resolved / ".bundle_version").read_text(encoding="utf-8") == "0.1.0"

    local_asset.write_text('{"name":"local update"}', encoding="utf-8")
    asset.write_text('{"name":"new bundle"}', encoding="utf-8")
    assert _paths._resolve_data_dir() == resolved
    assert local_asset.read_text(encoding="utf-8") == '{"name":"local update"}'
