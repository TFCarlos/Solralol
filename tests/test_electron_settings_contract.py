"""Regression checks for safe Electron access to the shared settings file."""

from __future__ import annotations

import json

import pytest

from app.services.settings_service import SettingsService
from backend.application import Application


def _service(tmp_path):
    service = SettingsService()
    service.settings_path = tmp_path / "settings.json"
    return service


def test_settings_snapshot_redacts_keys_and_patch_preserves_legacy_preferences(tmp_path):
    service = _service(tmp_path)
    service.settings_path.write_text(json.dumps({
        "riot_api_key": "RGAPI-secret",
        "gemini_api_key": "AIza-secret",
        "meta_region": "kr",
        "recording_quality": "720",
        "overlay_panels": {"gold": False, "alerts": True},
    }), encoding="utf-8")

    snapshot = service.electron_snapshot()
    assert snapshot["riot_api_key_configured"] is True
    assert snapshot["gemini_api_key_configured"] is True
    assert "riot_api_key" not in snapshot and "gemini_api_key" not in snapshot
    assert snapshot["recording_quality"] == "720"

    updated = service.update_electron_settings({"recording_auto": False})
    stored = json.loads(service.settings_path.read_text(encoding="utf-8"))
    assert updated["recording_auto"] is False
    assert stored["meta_region"] == "kr"
    assert stored["riot_api_key"] == "RGAPI-secret"
    assert stored["gemini_api_key"] == "AIza-secret"
    assert stored["overlay_panels"] == {"gold": False, "alerts": True}


def test_partial_overlay_update_keeps_other_panel_values(tmp_path):
    service = _service(tmp_path)
    service.settings_path.write_text(json.dumps({
        "overlay_panels": {"gold": False, "alerts": False, "threat": True, "purchase": False},
    }), encoding="utf-8")

    snapshot = service.update_electron_settings({"overlay_panels": {"alerts": True}})
    assert snapshot["overlay_panels"] == {"gold": False, "alerts": True, "purchase": False}
    assert service.load()["overlay_panels"]["threat"] is True  # obsolete preference remains in the user's file


def test_overlay_position_patch_preserves_other_panels_and_preferences(tmp_path):
    service = _service(tmp_path)
    service.settings_path.write_text(json.dumps({
        "overlay_positions": {"gold": [120, 200], "recall": [800, 250], "threat": [4, 5]},
        "recording_auto": False,
    }), encoding="utf-8")
    snapshot = service.update_electron_settings({"overlay_positions": {"gold": [240, 300]}})
    assert snapshot["overlay_positions"] == {"gold": [240, 300], "recall": [800, 250]}
    assert service.load()["overlay_positions"]["threat"] == [4, 5]
    assert service.load()["recording_auto"] is False


@pytest.mark.parametrize("changes", [
    {"recording_quality": "8k"},
    {"recording_bitrate": 9999},
    {"recording_size_limit_gb": 0},
    {"overlay_panel_scales": {"gold": 4.0}},
    {"overlay_panels": {"private": True}},
    {"riot_api_key": "must not be writable here"},
])
def test_invalid_and_unowned_settings_are_rejected(tmp_path, changes):
    service = _service(tmp_path)
    with pytest.raises(ValueError):
        service.update_electron_settings(changes)
    assert not service.settings_path.exists()


def test_failed_key_validation_does_not_replace_existing_credential(tmp_path, monkeypatch):
    service = _service(tmp_path)
    service.settings_path.write_text(json.dumps({"riot_api_key": "old-valid-key"}), encoding="utf-8")
    monkeypatch.setattr(service, "validate_riot_api_key", lambda _value: (False, "invalid"))

    valid, message, configured = service.store_validated_api_key("riot", "bad-key")
    assert (valid, message, configured) == (False, "invalid", True)
    assert service.load()["riot_api_key"] == "old-valid-key"


def test_key_validation_does_not_return_secret_to_renderer(tmp_path, monkeypatch):
    service = _service(tmp_path)
    monkeypatch.setattr(service, "validate_gemini_api_key", lambda _value: (True, "valid"))

    result = service.store_validated_api_key("gemini", "sensitive-value")
    assert result == (True, "valid", True)
    snapshot = service.electron_snapshot()
    assert snapshot["gemini_api_key_configured"] is True
    assert "sensitive-value" not in json.dumps(snapshot)


def test_application_settings_rpc_load_update_and_clear_stay_scoped(tmp_path, monkeypatch):
    app = Application()
    app.settings.settings_path = tmp_path / "settings.json"
    app.settings.save({"riot_api_key": "hidden", "meta_region": "kr"})

    loaded = app.dispatch("settings.load")
    assert loaded["riot_api_key_configured"] is True
    assert "riot_api_key" not in loaded
    updated = app.dispatch("settings.update", {"changes": {"recording_auto": False}})
    assert updated["recording_auto"] is False
    assert app.settings.load()["meta_region"] == "kr"

    app.dispatch("settings.key.clear", {"provider": "riot"})
    assert app.settings.load() == {"meta_region": "kr", "recording_auto": False}


def test_settings_screen_is_the_direct_electron_route():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    app_source = (root / "frontend/src/pages/App.tsx").read_text(encoding="utf-8")
    page_source = (root / "frontend/src/pages/SettingsPage.tsx").read_text(encoding="utf-8")
    assert "section === 'settings' && <SettingsPage backendReady={backendState === 'ready'} initialSection={settingsSection} />" in app_source
    assert "section !== 'settings'" in app_source
    assert "MIGRACIÓN EN CURSO" in app_source  # retained only for other unmigrated modules
    assert "<h1>Ajustes</h1>" in page_source
    for category in ("Cuenta y API", "Grabaciones", "Overlay y avisos"):
        assert category in page_source

