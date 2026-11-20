from __future__ import annotations

import json
import shutil

import pytest

from _paths import DATA_DIR
from app.services.draft_analyzer_service import DraftAnalyzerService
from app.services.identidad_campeon import ALIAS_CAMPEONES, IndiceIdentidadCampeon
from app.services.repositorio_campeones import RepositorioCampeones
from backend.draft_diagnostics import audit_draft_catalog
from backend.draft import DraftRuntime
from backend.application import Application
from app.services.repositorio_campeones import ConsultaCampeon, EstadoDatos


@pytest.fixture(scope="module")
def catalog():
    return list(json.loads((DATA_DIR / "champion_catalog.json").read_text(encoding="utf-8"))["data"].values())


def test_every_catalog_identity_and_alias_round_trips(catalog):
    index = IndiceIdentidadCampeon({row["id"]: row for row in catalog})
    assert not index.ambiguous
    assert len(index.entries) == len(catalog)
    for row in catalog:
        for value in (row["id"], row["name"], row["key"], row["name"].upper()):
            assert index.resolve(value) == row["id"]
        assert index.display_name(row["id"]) == row["name"]
        assert index.numeric_key(row["id"]) == int(row["key"])
    for alias, target in ALIAS_CAMPEONES.items():
        assert index.resolve(alias) == index.resolve(target)
    for value, expected in (("Aurelion Sol", "AurelionSol"), ("Wukong", "MonkeyKing"),
                            ("Monkey King", "MonkeyKing"), ("Nunu & Willump", "Nunu"),
                            ("Kai'Sa", "Kaisa"), ("Kog'Maw", "KogMaw"),
                            ("Cho'Gath", "Chogath"), ("Vel'Koz", "Velkoz"),
                            ("LeBlanc", "Leblanc"), ("Miss Fortune", "MissFortune"),
                            ("Twisted Fate", "TwistedFate"), ("Dr. Mundo", "DrMundo"),
                            ("Bel'Veth", "Belveth")):
        assert index.resolve(value) == expected


def test_legacy_file_paths_and_draft_sources_resolve_for_entire_catalog(catalog):
    root = DATA_DIR / "champion_data"
    repository = RepositorioCampeones(root)
    analyzer = DraftAnalyzerService(root)
    diagnostics = audit_draft_catalog(catalog, repository, analyzer)
    assert len(diagnostics) == len(catalog)
    assert all(row["status"] == "available" for row in diagnostics)
    assert len({repository.ruta(row["id"]) for row in catalog}) == len(catalog)
    for row in catalog:
        assert repository.ruta(row["id"]) == repository.ruta(row["name"])
        assert repository.ruta(row["id"]) == repository.ruta(row["key"])
        assert analyzer.get_champion_profile(row["id"]) is analyzer.get_champion_profile(row["name"])


def test_legacy_internal_id_filename_is_reused_without_duplicate_or_overwrite(tmp_path):
    source = DATA_DIR / "champion_data" / "wukong.json"
    legacy = tmp_path / "monkeyking.json"
    shutil.copy2(source, legacy)
    original = legacy.read_bytes()
    repository = RepositorioCampeones(tmp_path)
    assert repository.ruta("Wukong") == legacy
    assert repository.ruta("MonkeyKing") == legacy
    assert repository.obtener_campeon("62").estado.value == "AVAILABLE"
    assert legacy.read_bytes() == original
    assert len(repository.perfiles_globales()) == 1
    shutil.copy2(source, tmp_path / "wukong.json")
    reopened = RepositorioCampeones(tmp_path)
    assert len(reopened.perfiles_globales()) == 1
    assert "MonkeyKing" in reopened.duplicate_identities
    assert legacy.read_bytes() == original


@pytest.mark.parametrize("selected,role,expected", [
    ("AurelionSol", "mid", "AurelionSol"), ("Aurelion Sol", "mid", "AurelionSol"),
    ("MonkeyKing", "top", "MonkeyKing"), ("Wukong", "top", "MonkeyKing"),
])
def test_draft_snapshot_uses_existing_data_for_compound_names(monkeypatch, catalog, selected, role, expected):
    root = DATA_DIR / "champion_data"
    monkeypatch.setattr("backend.draft.DraftAnalyzerService", lambda: DraftAnalyzerService(root))
    monkeypatch.setattr("backend.draft.RepositorioCampeones", lambda: RepositorioCampeones(root))
    monkeypatch.setattr("backend.draft.resolve_meta_assets", lambda *args, **kwargs: {})
    runtime = DraftRuntime(catalog)
    runtime.lcu = type("Disconnected", (), {"is_connected": lambda self: False})()
    runtime._rune_assets = lambda *args, **kwargs: None
    snapshot = runtime.snapshot({"champion": selected, "role": role,
                                 "allies": [{"champion": selected, "role": role}]})
    analysis = snapshot["analysis"]
    assert snapshot["localChampion"] == expected
    assert analysis["variantStatus"] == "AVAILABLE"
    assert analysis["profileAvailable"] is True
    assert analysis["runes"] and analysis["builds"] and analysis["build"]["items"]
    assert analysis["situational"] and analysis["bans"]
    assert analysis["composition"]["damageSamples"] == 1
    assert analysis["powerCurve"]


def test_wukong_import_uses_numeric_key_and_existing_rune_page(monkeypatch, catalog):
    root = DATA_DIR / "champion_data"
    monkeypatch.setattr("backend.draft.DraftAnalyzerService", lambda: DraftAnalyzerService(root))
    monkeypatch.setattr("backend.draft.RepositorioCampeones", lambda: RepositorioCampeones(root))
    calls = []

    class LCU:
        def import_rune_page(self, *args, **kwargs):
            calls.append(("runes", args, kwargs))
            return True, "ok"

        def import_item_set(self, *args, **kwargs):
            calls.append(("build", args, kwargs))
            return True, "ok"

    runtime = DraftRuntime(catalog, LCU())
    assert runtime.import_selection({"champion": "Wukong", "role": "top", "kind": "runes", "pageIndex": 0})["ok"]
    assert runtime.import_selection({"champion": "MonkeyKing", "role": "top", "kind": "build", "pageIndex": 0})["ok"]
    assert calls[0][0] == "runes" and calls[0][1][1]
    assert calls[1][0] == "build" and calls[1][1][0] == 62
    assert calls[1][1][1] == "MonkeyKing" and calls[1][1][3]


def test_wukong_damage_uses_selected_role_variant():
    analyzer = DraftAnalyzerService(DATA_DIR / "champion_data")
    top = analyzer.get_champion_profile("Wukong", "top")["damage_breakdown"]
    jungle = analyzer.get_champion_profile("MonkeyKing", "jungle")["damage_breakdown"]
    assert top["physical_damage_percent"] == 79.2
    assert jungle["physical_damage_percent"] == 79.0
    assert analyzer.calculate_team_damage_breakdown(["MonkeyKing"], {"MonkeyKing": "jungle"})["physical"] == 79.0


def test_matchup_opponent_alias_uses_same_canonical_identity():
    analyzer = DraftAnalyzerService(DATA_DIR / "champion_data")
    displayed = analyzer.get_matchup_win_rate("Wukong", "Dr. Mundo")
    assert displayed != 50.0
    assert analyzer.get_matchup_win_rate("MonkeyKing", "DrMundo") == displayed
    assert analyzer.get_matchup_win_rate("62", "36") == displayed


def test_local_analysis_request_resolves_display_and_numeric_identity(catalog):
    calls = []
    app = Application.__new__(Application)
    app._catalog = catalog
    app.champions = type("Repo", (), {"consultar": lambda self, champion, lane, rank:
                         (calls.append((champion, lane, rank)) or ConsultaCampeon(EstadoDatos.SIN_DATOS_LOCALES))})()
    for selected in ("Wukong", "MonkeyKing", "62"):
        response = app._dispatch_active("champions.analysis", {"champion": selected, "lane": "top", "rank": "emerald_plus"})
        assert response["champion"] == "MonkeyKing"
    assert calls == [("MonkeyKing", "top", "emerald_plus")] * 3
