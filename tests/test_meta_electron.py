from __future__ import annotations

import json

import pytest
import requests

from app.services.meta_service import ServicioMeta
from backend.application import Application
from backend.contracts import BackendOperationError


def _application(tmp_path):
    app = Application()
    app.settings.settings_path = tmp_path / "settings.json"
    return app


def test_meta_bootstrap_preserves_original_region_preference(tmp_path):
    app = _application(tmp_path)
    app.settings.save({"meta_region": "kr", "recording_auto": True})

    result = app.dispatch("meta.bootstrap")

    assert result["region"] == "kr"
    assert [item["id"] for item in result["roles"]] == ["top", "jungle", "mid", "adc", "support"]
    assert {item["id"] for item in result["regions"]} == {"all", "euw", "na", "kr"}
    assert result["rank"] == "emerald_plus"


def test_meta_is_an_available_electron_destination():
    feature = next(item for item in Application().dispatch("app.bootstrap")["features"] if item["id"] == "meta")
    assert feature["status"] == "available"
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    page = (root / "frontend/src/pages/MetaPage.tsx").read_text(encoding="utf-8")
    shell = (root / "frontend/src/pages/App.tsx").read_text(encoding="utf-8")
    assert "Notas del parche" in page and "Tier list" in page
    assert "meta.tier" in page and "meta.notes" in page
    assert "section !== 'meta'" in shell


def test_meta_tier_uses_existing_service_and_persists_region(tmp_path):
    app = _application(tmp_path)
    app.settings.save({"meta_region": "euw", "recording_auto": True})

    class FakeMetaService:
        def obtener_lista_niveles(self, filters, force):
            return {"filters": filters, "force": force, "champions": [{"position": 1, "champion_id": "Karthus"}]}

    app._meta_service = FakeMetaService()
    result = app.dispatch("meta.tier", {"role": "jungle", "region": "all", "force": True})

    assert result["filters"] == {"role": "jungle", "region": "all"}
    assert result["champions"][0]["position"] == 1
    assert app.settings.load()["meta_region"] == "all"
    assert app.settings.load()["recording_auto"] is True


def test_meta_tier_reports_source_connection_failure_with_specific_code(tmp_path):
    app = _application(tmp_path)

    class OfflineMetaService:
        def obtener_lista_niveles(self, filters, force):
            raise requests.ConnectionError("network detail")

    app._meta_service = OfflineMetaService()
    with pytest.raises(BackendOperationError) as error:
        app.dispatch("meta.tier", {"role": "support", "region": "all"})
    assert error.value.code == "meta_source_unavailable"
    assert "LoLalytics" in str(error.value)


def test_meta_rejects_unsupported_filter_values(tmp_path):
    app = _application(tmp_path)
    with pytest.raises(ValueError, match="Posición"):
        app.dispatch("meta.tier", {"role": "aram", "region": "all"})
    with pytest.raises(ValueError, match="Región"):
        app.dispatch("meta.tier", {"role": "top", "region": "worldwide"})


def test_meta_notes_redact_local_path_and_attach_safe_cached_image(tmp_path):
    app = _application(tmp_path)
    hero = tmp_path / "patch_16.20_hero.png"
    hero.write_bytes(b"\x89PNG\r\n\x1a\nfixture")

    class FakeMetaService:
        VERSION_ESQUEMA_NOTAS = ServicioMeta.VERSION_ESQUEMA_NOTAS

        def obtener_notas(self, force):
            return {"version": "16.20", "hero_image_path": str(hero), "sections": []}

    app._meta_service = FakeMetaService()
    result = app.dispatch("meta.notes", {"force": False})

    assert result["hero_image"].startswith("data:image/png;base64,")
    assert "hero_image_path" not in result
    assert "D:" not in json.dumps(result)


def test_failed_patch_refresh_keeps_last_valid_cache(tmp_path):
    app = _application(tmp_path)
    cached = {"schema_version": ServicioMeta.VERSION_ESQUEMA_NOTAS, "version": "16.19", "sections": [{"title": "Campeones"}]}

    class FakeMetaService:
        VERSION_ESQUEMA_NOTAS = ServicioMeta.VERSION_ESQUEMA_NOTAS

        def obtener_notas(self, force):
            raise ConnectionError("offline")

        def cargar_cache(self, filename):
            assert filename == "patch_notes.json"
            return cached

    app._meta_service = FakeMetaService()
    result = app.dispatch("meta.notes", {"force": True})

    assert result["version"] == "16.19"
    assert result["cached"] is True
    assert result["stale"] is True


def test_replacing_patch_notes_only_removes_obsolete_patch_media(tmp_path):
    service = ServicioMeta.__new__(ServicioMeta)
    service.directorio = tmp_path
    old = tmp_path / "patch_16.19_hero.jpg"
    current = tmp_path / "patch_16.20_hero.png"
    unrelated = tmp_path / "champion_portrait.png"
    for path in (old, current, unrelated):
        path.write_bytes(b"image")

    service._eliminar_medios_parche_obsoletos(str(current))

    assert not old.exists()
    assert current.exists()
    assert unrelated.exists()


def test_meta_assets_only_resolve_catalog_champions_and_cached_data_dragon_icons(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from backend import assets

    data = tmp_path / "data"
    abilities = data / "champion_abilities"
    abilities.mkdir(parents=True)
    (data / "items.json").write_text(json.dumps({"items": {"1001": {"maps": {"11": True}}}}), encoding="utf-8")
    (abilities / "Ahri.json").write_text(json.dumps({"data": {"Ahri": {"passive": {"image": {"full": "AhriP.png"}}}}}), encoding="utf-8")
    cache = tmp_path / ".solralol" / "ddragon"
    paths = [cache / "champions" / "Ahri.png", cache / "items" / "16.20.1" / "1001.png", cache / "abilities" / "AhriP.png"]
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
    monkeypatch.setattr(assets, "DATA_DIR", data)
    monkeypatch.setattr(assets, "_version", lambda: "16.20.1")
    monkeypatch.setattr(assets, "_item_version", lambda: "16.20.1")
    monkeypatch.setattr(assets, "get_storage_manager", lambda: SimpleNamespace(ddragon_dir=cache))
    monkeypatch.setattr(assets, "_cached_or_download", lambda _url, path: path if path.is_file() else None)
    monkeypatch.setattr(assets, "_communitydragon_item_paths", lambda: {})

    result = assets.resolve_meta_assets(
        ["Ahri", "../../private"], ["1001", "9999"],
        [{"champion": "Ahri", "slot": "passive"}],
        [{"id": "Ahri", "name": "Ahri", "key": "103"}],
    )

    assert set(result) == {"champion:Ahri", "item:1001", "item:9999", "ability:Ahri|passive"}
    assert result["item:9999"] is None
    assert all(value.startswith("data:image/png;base64,") for value in result.values() if value)
