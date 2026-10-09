from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QTabWidget

from _paths import DATA_DIR
from app.services.match_analysis_grading import (
    calcular_grados_rendimiento,
    grado_desde_proporcion,
)
from app.services.match_analysis_models import (
    _componente_de_objetivo,
    _evaluar_runas,
    enriquecer_analisis_partida,
)
from app.ui.analisis_partida_ia import AnalisisPartidaIA

FIXTURE = Path(__file__).parent / "fixtures" / "briar_regression_match.json"


def _fixture() -> dict:
    """Carga la partida Briar conservada como regresión de coaching."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _puntuacion(total: int = 900, premio: str = "SVP") -> dict:
    """Construye puntuación final aislada del resultado y de los premios."""
    claves = ("combate", "economia", "objetivos", "vision", "supervivencia")
    categorias = {
        clave: {"final": total / 5, "reference": 200, "completeness": 0.8}
        for clave in claves
    }
    return {
        "state": "POSTGAME_FINAL",
        "players": [
            {
                "participant_id": "Briar",
                "total": total,
                "completeness": 0.8,
                "global_rank": 4,
                "awards": [premio],
                "categories": categorias,
            }
        ],
    }


@pytest.fixture(scope="module")
def aplicacion() -> QApplication:
    """Crea la aplicación Qt para las pruebas visuales sin abrir ventanas."""
    return QApplication.instance() or QApplication([])


def test_grado_estable_usa_referencia_y_conserva_excepcionales() -> None:
    escala = (
        (1.15, "A+"),
        (1.05, "A"),
        (0.95, "A-"),
        (0.85, "B+"),
        (0.75, "B"),
        (0.65, "B-"),
        (0.55, "C+"),
        (0.45, "C"),
        (0.35, "C-"),
        (0.25, "D+"),
        (0.15, "D"),
        (0.05, "D-"),
        (0.0, "F+"),
        (-0.01, "F-"),
    )
    assert all(grado_desde_proporcion(valor) == esperado for valor, esperado in escala)
    assert grado_desde_proporcion(1.3) == "A+"


def test_grado_final_no_depende_del_resultado_ni_del_premio() -> None:
    victoria = _puntuacion(900, "MVP")
    derrota = _puntuacion(900, "SVP")
    primero = calcular_grados_rendimiento(
        {"state": victoria["state"], "local_player": victoria["players"][0]}
    )
    segundo = calcular_grados_rendimiento(
        {"state": derrota["state"], "local_player": derrota["players"][0]}
    )
    assert primero == segundo
    assert primero["overall"] == "B+"
    assert victoria["players"][0]["total"] == 900
    assert calcular_grados_rendimiento({"state": "POSTGAME_PENDING"}) is None


def test_grado_requiere_cobertura_suficiente() -> None:
    incompleta = _puntuacion()
    incompleta["players"][0]["completeness"] = 0.2
    resumen = {"state": incompleta["state"], "local_player": incompleta["players"][0]}
    assert calcular_grados_rendimiento(resumen) is None
    pocas = _puntuacion()
    pocas["players"][0]["categories"] = {"combate": {"final": 300, "reference": 300}}
    resumen_pocas = {"state": pocas["state"], "local_player": pocas["players"][0]}
    assert calcular_grados_rendimiento(resumen_pocas) is None


def test_build_briar_critica_sinergia_y_valida_rutas_de_parche() -> None:
    fixture = _fixture()
    informe = enriquecer_analisis_partida(
        {"schema_version": 1, "analysis_type": "general_match_analysis", "summary": {}},
        fixture,
    )
    assert informe["build_archetype"] == "Núcleo ofensivo de letalidad y daño físico"
    assert informe["rune_evaluation"]["current"]["id"] == "8005"
    assert informe["rune_evaluation"]["alternative"]["id"] == "9923"
    assert "Mejorable" in informe["rune_evaluation"]["verdict"]
    assert "<" not in informe["rune_evaluation"]["alternative"]["mechanics"]
    assert (
        _evaluar_runas(fixture["user_stats"]["runes"], "16.20.1", "Build defensiva")[
            "alternative"
        ]
        is None
    )
    assert {revision["item_id"] for revision in informe["item_reviews"]} == {
        "6676",
        "3111",
        "6699",
        "3036",
        "6333",
        "1038",
    }
    catalogo = json.loads((DATA_DIR / "items.json").read_text(encoding="utf-8"))[
        "items"
    ]
    alternativas = informe["item_alternatives"]
    assert {alternativa["target_item_id"] for alternativa in alternativas} == {
        "3156",
        "3143",
    }
    for alternativa in alternativas:
        assert alternativa["recipe_valid"] is True
        assert _componente_de_objetivo(
            catalogo, alternativa["component_id"], alternativa["target_item_id"]
        )
        assert catalogo[alternativa["target_item_id"]]["gold"]["purchasable"]
        assert not alternativa["gold_on_hand_confirmed"]
    assert not _componente_de_objetivo(catalogo, "1057", "3143")
    assert all(
        "item_id" not in alternativa["mechanical_advantage"]
        for alternativa in alternativas
    )


def test_resumen_briar_resuelve_eventos_y_etiquetas_equipo() -> None:
    fixture = _fixture()
    informe = enriquecer_analisis_partida(
        {
            "schema_version": 1,
            "analysis_type": "general_match_analysis",
            "summary": {"main_turning_point": "event-396"},
        },
        fixture,
    )
    momentos = informe["summary"]["decisive_events"]
    assert momentos[0]["time_label"] == "31:10"
    assert "Briar muri" in momentos[0]["description"]
    assert momentos[1]["time_label"] == "31:16"
    assert momentos[1]["team_label"] == "El equipo rival"
    assert momentos[1]["seconds_after"] == 6
    assert "no demuestra causalidad" in informe["summary"]["main_turning_point"]
    fases = informe["game_phases"]
    assert any(
        "01:20" in str(evento) for evento in fases["early"].get("evidence_events", [])
    )
    assert any(
        "23:14" in str(evento) for evento in fases["mid"].get("evidence_events", [])
    )
    assert any(
        "28:02" in str(evento) for evento in fases["late"].get("evidence_events", [])
    )


def test_ui_resume_seguro_grados_responsive_y_rivales(aplicacion, monkeypatch) -> None:
    fixture = _fixture()
    fixture["performance_scoring"] = _puntuacion()
    monkeypatch.setattr(
        "app.services.match_log_service.MatchLogService.build_match_log",
        lambda _service, _session: copy.deepcopy(fixture),
    )
    resumen = enriquecer_analisis_partida(
        {
            "schema_version": 1,
            "analysis_type": "general_match_analysis",
            "summary": {"main_turning_point": "event-396"},
        },
        fixture,
    )
    session = {
        "session_id": "fixture-briar",
        "champion_name": "Briar",
        "player_name": "Jugador",
        "local_player_key": "Briar",
        "players": {
            "Briar": {"kills": 12, "deaths": 7, "assists": 4, "cs": 225, "win": False}
        },
        "final_scoreboard": {
            "Briar": {"kills": 12, "deaths": 7, "assists": 4, "cs": 225, "win": False}
        },
        "duration": 1971,
        "performance_scoring": fixture["performance_scoring"],
    }
    registro = {"saved_match_id": "fixture-briar", "model": "mock", "analysis": resumen}
    vista = AnalisisPartidaIA(session, registro)
    pestanas = vista.findChild(QTabWidget, "matchAnalysisSections")
    assert pestanas is not None and pestanas.count() == 6
    vista.resize(1366, 768)
    vista.show()
    aplicacion.processEvents()
    textos = [etiqueta.text() for etiqueta in vista.findChildren(QLabel)]
    visible = " ".join(textos)
    assert "CHAOS" not in visible and "ORDER" not in visible
    assert "event-396" not in visible and "31:10" in visible and "31:16" in visible
    assert "Grado · B+" in visible
    assert "12/7/4" in visible
    assert "A+" in " ".join(textos) or "B+" in visible
    assert len(vista.findChildren(QPushButton)) >= 5
    tarjetas = {}
    for tarjeta in vista.findChildren(QFrame, "matchAnalysisCard"):
        if tarjeta.layout() and tarjeta.layout().count():
            titulo = tarjeta.layout().itemAt(0).widget()
            if isinstance(titulo, QLabel):
                tarjetas[titulo.text()] = tarjeta
    assert (
        tarjetas["Qué funcionó"].sizeHint().height()
        < tarjetas["Lectura del partido"].sizeHint().height()
    )
    scroll_vertical_maximos = []
    for ancho, alto in ((1366, 768), (1600, 900), (1920, 1080), (2560, 1440)):
        vista.resize(ancho, alto)
        aplicacion.processEvents()
        assert vista.width() == ancho and 700 <= vista.height() <= alto
        for pagina in range(pestanas.count()):
            pestanas.setCurrentIndex(pagina)
            aplicacion.processEvents()
            assert (
                pestanas.widget(pagina).horizontalScrollBarPolicy().name
                == "ScrollBarAlwaysOff"
            )
            scroll_vertical_maximos.append(
                pestanas.widget(pagina).verticalScrollBar().maximum()
            )
    assert max(scroll_vertical_maximos) > 0
    vista.close()


def test_resuelve_iconos_locales_sin_servicio_remoto(aplicacion) -> None:
    vista = AnalisisPartidaIA(
        {"session_id": "fixture-icons", "champion_name": "Briar"},
        {
            "saved_match_id": "fixture-icons",
            "analysis": {
                "schema_version": 1,
                "analysis_type": "general_match_analysis",
                "summary": {},
            },
        },
    )
    rutas = (
        vista.get_champion_icon("Yasuo"),
        vista.get_item_icon("6676"),
        vista.get_rune_icon("Ataque intensificado"),
        vista.get_rune_icon("Lluvia de cuchillas"),
        vista.get_spell_icon("Flash"),
        vista.get_ability_icon("Briar", "Q"),
    )
    assert all(ruta and Path(ruta).is_file() for ruta in rutas)
    etiqueta = vista._icono("item", "6676")
    assert etiqueta.pixmap() is not None and not etiqueta.pixmap().isNull()
    assert "6676" not in vista._sanear_texto(
        "Comparar el objeto 6676 antes del siguiente regreso"
    )
    assert vista._etiqueta_grado("A+").property("banda") == "A"
    seguro = vista._etiqueta("<img src=x onerror=alert(1)>")
    assert seguro.textFormat().name == "PlainText"
    assert "<img" in seguro.text()
    vista.close()
