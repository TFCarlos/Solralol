from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QTabWidget

from _paths import DATA_DIR
from app.services.match_analysis_evidence_service import MatchAnalysisEvidenceService
from app.services.match_analysis_models import (
    VERSION_ESQUEMA_ANALISIS,
    enriquecer_analisis_partida,
    validar_analisis_partida,
)
from app.ui.analisis_partida_ia import AnalisisPartidaIA

FIXTURE = Path(__file__).parent / "fixtures" / "briar_regression_match.json"


@pytest.fixture(scope="module")
def partida_briar() -> dict[str, Any]:
    """Carga el registro completo anonimizado de la partida real de Briar."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _application() -> QApplication:
    """Devuelve QApplication para ejecutar el smoke test fuera de pantalla."""
    return QApplication.instance() or QApplication([])


def _payload_v2() -> dict[str, Any]:
    """Crea un informe Gemini v2 intencionalmente parcial para probar fallbacks."""
    return {
        "schema_version": 2,
        "analysis_type": "general_match_analysis",
        "summary": {
            "short_summary": "Briar convirtió varias bajas en control temporal."
        },
        "game_phases": {},
        "performance": {},
        "key_enemies": [],
        "next_game_priorities": [],
        "item_reviews": [],
        "item_alternatives": [],
        "rune_comments": [],
    }


def _sesion_guardada(partida: dict[str, Any]) -> dict[str, Any]:
    """Adapta el log anonimizado a la sesión que consume el panel Qt."""
    jugadores = {}
    marcador = {}
    for jugador in partida["all_players"]:
        final = {
            "kills": jugador["kills"],
            "deaths": jugador["deaths"],
            "assists": jugador["assists"],
            "cs_total": jugador["cs"],
            "gold_earned": jugador["gold"],
            "total_damage_dealt_to_champions": jugador["damage_to_champions"],
            "damage_dealt_to_objectives": jugador.get("damage_to_objectives"),
            "damage_taken": jugador.get("damage_taken"),
            "damage_self_mitigated": jugador.get("damage_self_mitigated"),
            "vision_score": jugador.get("vision_score"),
            "items": jugador["items"],
            "win": not jugador["is_ally"],
        }
        jugadores[jugador["player_key"]] = {
            "player_key": jugador["player_key"],
            "team": jugador["team"],
            "role": jugador["role"],
            "champion_name": jugador["champion"],
            "items": jugador["items"],
            "runes": jugador.get("runes", {}),
            "summoner_spells": jugador.get("summoner_spells", {}),
            "win": not jugador["is_ally"],
            "final": final,
        }
        marcador[jugador["player_key"]] = final
    return {
        "session_id": partida["metadata"]["session_id"],
        "champion_name": partida["metadata"]["champion_name"],
        "player_riot_id": "Jugador",
        "game_version": partida["metadata"]["game_version"],
        "duration": partida["metadata"]["duration_seconds"],
        "local_team": partida["metadata"]["local_team"],
        "winning_team": partida["metadata"]["winning_team"],
        "local_player_key": partida["local_player_key"],
        "players": jugadores,
        "final_scoreboard": marcador,
        "events": partida["events_chronology"],
        "snapshots": [],
    }


class AssetsLocales:
    """Simula la interfaz de assets con imágenes reales del catálogo local."""

    version = "16.20.1"

    def __init__(self) -> None:
        """Prepara índices locales de objetos conocidos."""
        catalog = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
        self.items = {int(clave): clave for clave in catalog["items"]}

    def resolve_champion_id(self, nombre: str) -> str | None:
        """Resuelve el alias mediante el catálogo canónico de campeones."""
        return MatchAnalysisEvidenceService._canonical_champion_id(nombre)

    def champion_url(self, nombre: str) -> str:
        """Devuelve el archivo de retrato canónico local."""
        ruta = DATA_DIR / "champion_icons" / f"{nombre}.png"
        return str(ruta)

    def item_url(self, item_id: int) -> str:
        """Devuelve el archivo de objeto local."""
        return str(DATA_DIR / "item_icons" / f"{item_id}.png")


def test_evidencia_cubre_roster_eventos_compras_y_anonimiza(
    partida_briar: dict[str, Any],
) -> None:
    evidencia = MatchAnalysisEvidenceService().build_evidence(partida_briar)
    serializada = json.dumps(evidencia, ensure_ascii=False)

    assert evidencia["coverage"]["participants"] == 10
    assert evidencia["coverage"]["events"] == 553
    assert evidencia["coverage"]["gold_on_hand_available"] is False
    assert evidencia["player"]["champion_id"] == "Briar"
    assert {valor["champion_id"] for valor in evidencia["participants"]} >= {
        "Naafiri",
        "Yasuo",
        "Viktor",
        "Lulu",
        "TahmKench",
    }
    assert {evento["time_label"] for evento in evidencia["player_deaths"]} >= {
        "01:20",
        "03:24",
        "06:31",
        "31:10",
    }
    assert any(
        evento["time_label"] == "23:14" and "Bar" in evento["objective"]
        for evento in evidencia["objective_events"]
    )
    assert any(
        evento["time_label"] == "28:02" and "Inhibidor" in evento["objective"]
        for evento in evidencia["structure_events"]
    )
    assert any(
        evento["time_label"] == "31:16" and "Bar" in evento["objective"]
        for evento in evidencia["objective_events"]
    )
    assert all(
        clave.startswith(("ally_", "enemy_", "player_local"))
        for clave in {
            participante["player_key"] for participante in evidencia["participants"]
        }
    )
    assert "Solrasar#000" not in serializada
    assert "riot_id" not in serializada
    assert evidencia["coverage"]["runes_available"] is True
    assert evidencia["coverage"]["runes_source"] == "user-provided-task-context"


def test_fallback_rellena_cinco_rivales_fases_build_y_prioridades_con_hechos(
    partida_briar: dict[str, Any],
) -> None:
    informe = enriquecer_analisis_partida(_payload_v2(), partida_briar)
    rivales = {rival["champion_name"]: rival for rival in informe["key_enemies"]}

    assert len(rivales) == 5
    assert rivales["Naafiri"]["role"] == "JUNGLE"
    assert "directo" in rivales["Naafiri"]["matchup_note"]
    assert rivales["Yasuo"]["threat_level"] == "alta"
    assert rivales["Viktor"]["threat_level"] == "alta"
    assert rivales["Lulu"]["kda"]["assists"] == 24
    assert "24 asistencias" in rivales["Lulu"]["why_it_was_a_problem"]
    assert rivales["Tahm Kench"]["champion_id"] == "TahmKench"
    assert all(rival["dangerous_abilities"] for rival in rivales.values())
    assert all(
        habilidad["observed_cast"] is False
        for rival in rivales.values()
        for habilidad in rival["dangerous_abilities"]
    )

    fases = informe["game_phases"]
    assert {evento["time_label"] for evento in fases["early"]["evidence_events"]} >= {
        "01:20",
        "03:24",
        "06:31",
    }
    assert "08:50" in fases["early"]["summary"]
    assert any(
        evento["time_label"] == "23:14" for evento in fases["mid"]["evidence_events"]
    )
    assert "28:02" in fases["late"]["summary"]
    assert {evento["time_label"] for evento in fases["late"]["evidence_events"]} >= {
        "28:02",
        "29:43",
        "31:10",
        "31:16",
    }
    assert all(
        "event_id" in evento
        for fase in fases.values()
        for evento in fase["evidence_events"]
    )

    revisiones = {item["item_id"]: item for item in informe["item_reviews"]}
    assert set(revisiones) == {"6676", "3111", "6699", "3036", "6333", "1038"}
    assert revisiones["6676"]["catalog_patch"] == "16.20.1"
    assert revisiones["3036"]["purchase_time"] == "22:10"
    alternativa = informe["item_alternatives"][0]
    assert alternativa["item_id"] == "3156"
    assert alternativa["component_id"] == "1033"
    assert alternativa["target_item_id"] == "3156"
    assert alternativa["replace_or_delay_item_id"] == "1038"
    assert alternativa["recipe_valid"] is True
    assert alternativa["gold_on_hand_confirmed"] is False
    assert informe["rune_evaluation"]["current"]["id"] == "8005"
    assert informe["rune_evaluation"]["alternative"]["id"] == "9923"

    prioridades = informe["next_game_priorities"]
    assert len(prioridades) >= 3
    assert prioridades[0]["evidence_refs"] == ["event-535", "event-541"]
    assert (
        "31:10" in prioridades[0]["evidence"] and "31:16" in prioridades[0]["evidence"]
    )
    assert "posición" not in prioridades[0]["concrete_action"].casefold()
    assert "Bar" in informe["summary"]["main_turning_point"]
    assert "225" in informe["summary"]["short_summary"]
    assert "33,386" in informe["summary"]["short_summary"]
    assert "12 bajas" in informe["summary"]["short_summary"]
    assert "12 asistencias" not in informe["summary"]["short_summary"]
    assert informe["schema_version"] == VERSION_ESQUEMA_ANALISIS
    assert informe["match_evidence"]["coverage"]["position_data_available"] is False


def test_prioridades_modelo_sin_eventos_validos_se_reemplazan_por_fallback(
    partida_briar: dict[str, Any],
) -> None:
    payload = _payload_v2()
    payload["next_game_priorities"] = [
        {
            "title": f"Consejo genérico {indice}",
            "explanation": "El consejo no aporta ninguna referencia temporal.",
            "concrete_action": "Juega con más cuidado.",
            "evidence_refs": ["event-999999"],
        }
        for indice in range(3)
    ]
    informe = enriquecer_analisis_partida(payload, partida_briar)

    assert all(
        not prioridad["title"].startswith("Consejo genérico")
        for prioridad in informe["next_game_priorities"]
    )
    assert {"event-535", "event-541"} <= set(
        informe["next_game_priorities"][0]["evidence_refs"]
    )


def test_catalogo_local_resuelve_retratos_y_habilidades_de_los_cinco_enemigos(
    partida_briar: dict[str, Any],
) -> None:
    assets = AssetsLocales()
    catalogo = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
    informe = enriquecer_analisis_partida(_payload_v2(), partida_briar)
    rivales = {rival["champion_name"]: rival for rival in informe["key_enemies"]}

    for nombre, rival in rivales.items():
        ruta_retrato = DATA_DIR / "champion_icons" / f"{rival['champion_id']}.png"
        assert assets.resolve_champion_id(nombre) == rival["champion_id"]
        assert ruta_retrato.is_file()
        for habilidad in rival["dangerous_abilities"]:
            ruta_habilidad = (
                DATA_DIR
                / "ability_icons"
                / f"{rival['champion_id']}{habilidad['slot']}.png"
            )
            assert ruta_habilidad.is_file()
    for item_id in (6676, 3111, 6699, 3036, 6333, 1038, 3340):
        assert str(item_id) in catalogo["items"]
        assert (DATA_DIR / "item_icons" / f"{item_id}.png").is_file()


def test_informes_antiguos_siguen_validos_y_se_enriquecen_sin_reescritura(
    partida_briar: dict[str, Any],
) -> None:
    antiguo = {
        "schema_version": 1,
        "analysis_type": "general_match_analysis",
        "summary": {"short_summary": "Conclusión original del informe guardado."},
    }
    informe = enriquecer_analisis_partida(antiguo, partida_briar)

    assert validar_analisis_partida(antiguo)["schema_version"] == 1
    assert informe["schema_version"] == VERSION_ESQUEMA_ANALISIS
    assert informe["summary"]["short_summary"].startswith(
        "Conclusión original del informe guardado."
    )
    assert "Hechos del registro:" in informe["summary"]["short_summary"]
    assert len(informe["key_enemies"]) == 5
    assert len(informe["next_game_priorities"]) >= 3
    assert antiguo["schema_version"] == 1
    assert (
        antiguo["summary"]["short_summary"]
        == "Conclusión original del informe guardado."
    )


def test_panel_muestra_las_seis_pestanas_con_iconos_y_contenido_en_fallback(
    partida_briar: dict[str, Any],
) -> None:
    aplicacion = _application()
    session = _sesion_guardada(partida_briar)
    registro = {
        "saved_match_id": session["session_id"],
        "schema_version": 1,
        "provider": "Gemini",
        "model": "gemini-flash-lite-latest",
        "created_at": "2026-10-08T18:00:00+00:00",
        "analysis": {
            "schema_version": 1,
            "analysis_type": "general_match_analysis",
            "summary": {"short_summary": "Informe guardado antiguo."},
        },
    }
    assets = AssetsLocales()
    catalogo = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
    vista = AnalisisPartidaIA(session, registro, assets=assets, item_catalog=catalogo)
    vista.resize(1480, 920)
    vista.show()
    aplicacion.processEvents()

    pestanas = vista.findChild(QTabWidget, "matchAnalysisSections")
    assert pestanas is not None and pestanas.count() == 6
    assert [pestanas.tabText(indice) for indice in range(6)] == [
        "Resumen",
        "Fases",
        "Rendimiento",
        "Build",
        "Rivales",
        "Mejoras",
    ]
    botones = vista.findChildren(QFrame, "matchAnalysisCard")
    assert len(vista.analisis["key_enemies"]) == 5
    assert len(vista.analisis["next_game_priorities"]) >= 3
    assert botones
    assert all(
        pestanas.widget(indice).findChildren(QFrame, "matchAnalysisCard")
        for indice in range(6)
    )
    iconos = vista.findChildren(QLabel, "matchAnalysisIcon")
    assert iconos
    assert any(icono.pixmap() and not icono.pixmap().isNull() for icono in iconos)
    assert vista._estadisticas_factuales().startswith("KDA 12/7/4")
    assert "12/7/4" in vista._estadisticas_factuales()
    assert not vista._estadisticas_factuales().startswith("KDA 4/7/12")
    for pesta in range(pestanas.count()):
        pestanas.setCurrentIndex(pesta)
        aplicacion.processEvents()
        assert pestanas.widget(pesta).verticalScrollBar().maximum() >= 0


def test_panel_no_falla_si_faltan_assets_o_nuevos_campos(
    partida_briar: dict[str, Any],
) -> None:
    _application()
    session = _sesion_guardada(partida_briar)
    registro = {
        "saved_match_id": session["session_id"],
        "analysis": {
            "schema_version": 1,
            "analysis_type": "general_match_analysis",
            "summary": {},
        },
    }
    vista = AnalisisPartidaIA(session, registro)
    assert vista.findChild(QTabWidget, "matchAnalysisSections").count() == 6
    assert len(vista.findChildren(QFrame, "matchAnalysisCard")) > 0
    assert vista.findChildren(QLabel, "matchAnalysisIcon")


def test_helpers_iconicos_resuelven_campeon_objeto_runa_hechizo_y_habilidad(
    monkeypatch: pytest.MonkeyPatch, partida_briar: dict[str, Any]
) -> None:
    _application()
    from app.services.data_dragon_assets import DataDragonAssetService

    def cargar_catalogos(servicio: DataDragonAssetService) -> None:
        servicio.champions = {"Yasuo": "Yasuo"}

    monkeypatch.setattr(DataDragonAssetService, "_load_catalogs", cargar_catalogos)
    assets = DataDragonAssetService()
    assert assets.resolve_champion_id("Tahm Kench") == "TahmKench"
    assert assets.resolve_champion_id("Yasuo") == "Yasuo"
    assert "TahmKench.png" in assets.champion_url("Tahm Kench")

    session = _sesion_guardada(partida_briar)
    report = {
        "saved_match_id": session["session_id"],
        "analysis": {
            "schema_version": 1,
            "analysis_type": "general_match_analysis",
            "summary": {},
        },
    }
    catalog = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))
    panel = AnalisisPartidaIA(
        session, report, assets=AssetsLocales(), item_catalog=catalog
    )
    assert Path(panel.get_champion_icon("Tahm Kench") or "").is_file()
    assert Path(panel.get_item_icon("6676") or "").is_file()
    assert Path(panel.get_rune_icon("Press the Attack") or "").is_file()
    assert Path(panel.get_spell_icon("Flash") or "").is_file()
    assert Path(panel.get_ability_icon("Yasuo", "W") or "").is_file()
    assert panel.get_ability_icon("UnknownChampion", "W") is None
    panel.close()
    assets.deleteLater()
