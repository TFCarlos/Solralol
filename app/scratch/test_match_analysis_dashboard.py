from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QMessageBox,
    QPushButton,
    QTabWidget,
)

from app.services.live_match_tracker import LiveMatchTracker
from app.services.match_ai_analyzer_service import (
    ESQUEMA_ANALISIS_GEMINI,
    ErrorSolicitudGemini,
    MatchAIAnalyzerService,
)
from app.services.match_analysis_models import (
    enriquecer_analisis_partida,
    validar_analisis_partida,
)
from app.ui.analisis_partida_ia import AnalisisPartidaIA
from app.ui.live_match_analysis_dialog import LiveMatchAnalysisDialog


@pytest.fixture
def payload() -> dict:
    return {
        "schema_version": 1,
        "analysis_type": "general_match_analysis",
        "summary": {
            "overall_grade": "A",
            "short_summary": "Buena presion lateral.",
            "strengths": ["Buen farmeo"],
            "weaknesses": ["Recall tard?o"],
            "key_takeaway": "Sincroniza los recalls.",
        },
        "game_phases": {
            "early": {"assessment": "Ventaja", "recommendations": ["Congela la oleada"]}
        },
        "farming": {
            "assessment": "Buen ritmo de súbditos.",
            "recommendations": ["Mantén la presión lateral."],
        },
        "itemization": {
            "strengths": ["Build coherente"],
            "mistakes": [],
            "alternative_items": ["Resistencia mágica"],
        },
        "objective_conversion": {
            "assessment": "Convierte la prioridad en visión.",
            "recommendations": ["Asegura visión antes del dragón."],
        },
        "enemy_matchups": [
            {
                "champion_id": nombre,
                "difficulty": "Dificil",
                "assessment": "Amenaza en corto alcance.",
                "counterplay": ["Mantener distancia"],
                "mistakes": [],
                "recommendations": [],
            }
            for nombre in ("Darius", "Garen", "Lux", "Ashe", "Nautilus")
        ],
        "improvement_priorities": [
            {
                "title": "Recall",
                "explanation": "Gasta oro antes del objetivo.",
                "priority": "high",
                "action": "Regresa tras empujar la oleada.",
            }
        ],
    }


def _registro(session_id: str, analysis: dict) -> dict:
    return {
        "saved_match_id": session_id,
        "analysis_type": "general_match_analysis",
        "schema_version": 1,
        "provider": "Gemini",
        "model": "gemini-flash",
        "created_at": "2026-10-08T10:00:00+00:00",
        "last_successful_analysis_at": "2026-10-08T10:00:00+00:00",
        "source_fingerprint": "test-fingerprint",
        "status": "complete",
        "analysis": analysis,
        "source_response": json.dumps(analysis),
    }


def test_valida_esquema_y_conserva_campos_opcionales_ausentes(payload: dict) -> None:
    payload.pop("farming")
    payload.pop("itemization")
    payload.pop("objective_conversion")
    validado = validar_analisis_partida(payload)
    assert validado["summary"]["overall_grade"] == "A"
    assert "farming" not in validado
    assert "late" not in validado["game_phases"]


@pytest.mark.parametrize(
    "cambio",
    [
        {"schema_version": 99},
        {"analysis_type": "other"},
        {"summary": []},
        {"summary": {"short_summary": 42}},
    ],
)
def test_rechaza_estructura_invalida(payload: dict, cambio: dict) -> None:
    payload.update(cambio)
    with pytest.raises((TypeError, ValueError)):
        validar_analisis_partida(payload)


def test_persistencia_restauracion_y_borrado_cascada(tmp_path, payload: dict) -> None:
    tracker = LiveMatchTracker({}, persist=False)
    tracker.sessions_path = tmp_path / "matches.json"
    tracker._save_sessions(
        [
            {"session_id": "match-a", "players": {}, "snapshots": []},
            {"session_id": "match-b", "players": {}, "snapshots": []},
        ]
    )
    informe = enriquecer_analisis_partida(payload)
    tracker.guardar_analisis_partida("match-a", _registro("match-a", informe))

    restaurado = LiveMatchTracker({}, persist=False)
    restaurado.sessions_path = tracker.sessions_path
    partidas = restaurado.load_saved_sessions()
    assert (
        partidas[0]["ai_match_analysis"]["analysis"]["summary"]["overall_grade"] == "A"
    )
    assert partidas[0]["ai_match_analysis"]["analysis"]["next_game_priorities"]
    assert "ai_match_analysis" not in partidas[1]

    restaurado.delete_saved_session("match-a")
    assert [partida["session_id"] for partida in restaurado.load_saved_sessions()] == [
        "match-b"
    ]


def test_fallo_de_validacion_no_reemplaza_analisis_previo(
    tmp_path, payload: dict
) -> None:
    tracker = LiveMatchTracker({}, persist=False)
    tracker.sessions_path = tmp_path / "matches.json"
    anterior = _registro("match-a", payload)
    tracker._save_sessions(
        [
            {
                "session_id": "match-a",
                "players": {},
                "snapshots": [],
                "ai_match_analysis": anterior,
            }
        ]
    )
    invalido = _registro("match-a", {"schema_version": 99})

    with pytest.raises((TypeError, ValueError)):
        tracker.guardar_analisis_partida("match-a", invalido)

    assert tracker.load_saved_sessions()[0]["ai_match_analysis"] == anterior


def test_servicio_parsea_json_y_calcula_huella(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(
        "app.services.match_ai_analyzer_service.MatchLogService.get_match_log",
        lambda _servicio, _sesion: ({}, "registro de prueba"),
    )
    servicio = MatchAIAnalyzerService()
    monkeypatch.setattr(
        servicio,
        "_call_gemini_api",
        lambda _prompt, _key: (json.dumps(payload), "gemini-flash"),
    )

    analysis, response, model, fingerprint = servicio.analyze_match(
        {"session_id": "m"}, "key"
    )

    assert analysis["summary"]["overall_grade"] == "A"
    assert json.loads(response)["schema_version"] == 1
    assert model == "gemini-flash"
    assert len(fingerprint) == 64
    assert analysis["key_enemies"]
    assert analysis["next_game_priorities"]


def test_enriquece_informe_completo_con_todas_las_secciones(payload: dict) -> None:
    payload["summary"].update(
        champion_name="Garen",
        player_name="Jugador",
        main_error="Entró sin visión.",
        core_priority="Preparar los objetivos.",
    )
    payload["performance"] = {
        "vision": {"assessment": "Visión limitada.", "tip": "Limpia antes del dragón."}
    }
    payload["game_phases"]["early"].update(
        title="Ventaja inicial",
        what_worked="Presionó la oleada.",
        what_failed="No colocó visión.",
        adaptation="Asegura río antes de avanzar.",
    )
    payload["key_enemies"] = [
        {
            "champion_name": "Darius",
            "role": "TOP",
            "threat_level": "high",
            "why_it_was_a_problem": "Ganaba intercambios extendidos.",
            "strengths": ["Presión sostenida"],
            "dangerous_tools": ["Q", "R"],
            "how_to_play_against": "Intercambia corto y guarda distancia.",
        }
    ]
    payload["next_game_priorities"] = [
        {
            "title": f"Prioridad {indice}",
            "explanation": "La visión facilitó una rotación rival.",
            "concrete_action": "Coloca un guardián antes del objetivo.",
            "context_type": "vision",
        }
        for indice in range(3)
    ]

    resultado = enriquecer_analisis_partida(payload)

    assert resultado["summary"]["champion_name"] == "Garen"
    assert resultado["game_phases"]["early"]["what_failed"] == "No colocó visión."
    assert resultado["performance"]["vision"]["tip"] == "Limpia antes del dragón."
    assert resultado["key_enemies"][0]["champion_name"] == "Darius"
    assert resultado["key_enemies"][0]["dangerous_tools"] == ["Q", "R"]
    assert len(resultado["next_game_priorities"]) == 3


def test_completa_rivales_y_tres_prioridades_desde_contexto_observado(
    payload: dict,
) -> None:
    payload.pop("enemy_matchups")
    payload.pop("improvement_priorities")
    payload["key_enemies"] = [
        {
            "champion_name": "Zed",
            "role": "MID",
            "why_it_was_a_problem": "Amenaza declarada por el modelo.",
            "how_to_play_against": "Guarda el destello.",
        }
    ]
    payload["summary"]["short_summary"] = "Se perdió presión antes de los objetivos."
    contexto = {
        "champion_name": "Garen",
        "player_name": "Jugador",
        "local_player_key": "local",
        "user_stats": {
            "role": "TOP",
            "deaths": 3,
            "kills": 1,
            "assists": 2,
            "cs_per_min": 4.2,
            "vision_score": 17,
            "items": ["3006"],
        },
        "all_players": [
            {
                "player_key": "local",
                "champion": "Garen",
                "role": "TOP",
                "is_ally": True,
            },
            {
                "player_key": "enemy-top",
                "champion": "Darius",
                "role": "TOP",
                "is_ally": False,
            },
            {
                "player_key": "enemy-jg",
                "champion": "Lee Sin",
                "role": "JUNGLE",
                "is_ally": False,
            },
        ],
        "events_chronology": [
            {
                "time_seconds": 620,
                "type": "kill",
                "killer_key": "enemy-top",
                "victim_key": "local",
            },
            {"time_seconds": 1190, "type": "objective", "objective": "dragon"},
        ],
    }

    resultado = enriquecer_analisis_partida(payload, contexto)

    assert resultado["key_enemies"][0]["champion_name"] == "Darius"
    assert resultado["key_enemies"][0]["role"] == "TOP"
    assert "Te elimin" in resultado["key_enemies"][0]["why_it_was_a_problem"]
    assert len(resultado["next_game_priorities"]) >= 3
    assert (
        "objetivos" in resultado["game_phases"]["mid"]["summary"]
        or "Te elimin" in resultado["game_phases"]["mid"]["summary"]
    )
    assert "farming" in resultado["performance"]


def test_esquema_gemini_usa_tipos_json_schema_y_solicitud_serializable(
    monkeypatch,
) -> None:
    servicio = MatchAIAnalyzerService()
    monkeypatch.setattr(
        servicio, "_get_available_models", lambda _key: ["gemini-flash"]
    )
    capturado = {}

    class Respuesta:
        status_code = 200

        def json(self):
            return {
                "candidates": [{"content": {"parts": [{"text": '{"ok": true}' * 8}]}}]
            }

    def publicar(url, json, headers, timeout):
        capturado.update(url=url, payload=json, headers=headers, timeout=timeout)
        return Respuesta()

    monkeypatch.setattr(
        "app.services.match_ai_analyzer_service.requests.post", publicar
    )
    respuesta, modelo = servicio._call_gemini_api("prompt", "test-api-key")

    assert modelo == "gemini-flash"
    assert respuesta.startswith('{"ok": true}')
    assert "?key=" not in capturado["url"]
    assert capturado["headers"]["x-goog-api-key"] == "test-api-key"
    assert (
        capturado["payload"]["generationConfig"]["responseFormat"]["text"]["mimeType"]
        == "APPLICATION_JSON"
    )
    esquema = capturado["payload"]["generationConfig"]["responseFormat"]["text"][
        "schema"
    ]
    assert esquema == ESQUEMA_ANALISIS_GEMINI
    assert esquema["type"] == "object"
    assert esquema["properties"]["enemy_matchups"]["items"]["type"] == "object"
    assert json.dumps(capturado["payload"])
    propiedades = capturado["payload"]["generationConfig"]["responseFormat"]["text"][
        "schema"
    ]["properties"]
    assert "key_enemies" in propiedades
    assert "next_game_priorities" in propiedades
    assert "performance" in propiedades
    assert "responseMimeType" not in capturado["payload"]["generationConfig"]
    assert "responseSchema" not in capturado["payload"]["generationConfig"]
    assert "/v1beta/models/gemini-flash:generateContent" in capturado["url"]


def test_http_400_formato_json_es_no_reintentable_y_diagnosticable(
    monkeypatch,
) -> None:
    servicio = MatchAIAnalyzerService()
    monkeypatch.setattr(
        servicio,
        "_get_available_models",
        lambda _key: ["gemini-flash-lite-latest", "otro"],
    )
    llamadas = []

    class Respuesta:
        status_code = 400
        text = "diagnóstico completo"

        def __init__(self):
            self.headers = {"x-goog-request-id": "request-123"}

        def json(self):
            return {
                "error": {
                    "code": 400,
                    "status": "INVALID_ARGUMENT",
                    "message": "Invalid value at 'generation_config.response_format.text.mime_type' (type.googleapis.com/google.ai.generativelanguage.v1beta.TextResponseFormat.MimeType), \"application/json\"",
                }
            }

    def publicar(*args, **kwargs):
        llamadas.append((args, kwargs))
        return Respuesta()

    monkeypatch.setattr(
        "app.services.match_ai_analyzer_service.requests.post", publicar
    )
    with pytest.raises(ErrorSolicitudGemini) as error:
        servicio._call_gemini_api("prompt", "private-api-key")

    diagnostico = error.value.diagnostico
    assert len(llamadas) == 1
    assert diagnostico["http_status"] == 400
    assert diagnostico["category"] == "INVALID_ARGUMENT"
    assert diagnostico["field_path"] == (
        "generation_config.response_format.text.mime_type"
    )
    assert diagnostico["request_id"] == "request-123"
    assert diagnostico["model"] == "gemini-flash-lite-latest"
    assert diagnostico["retryable"] is False
    assert error.value.reintentable is False
    assert '"application/json"' in diagnostico["message"]
    assert "private-api-key" not in str(error.value)


def test_error_http_400_restaura_la_vista_y_muestra_detalle_espanol(
    monkeypatch, payload: dict
) -> None:
    aplicacion = QApplication.instance() or QApplication([])
    dialogo = QDialog()
    dialogo.is_analyzing_ai = True
    dialogo._closed = False
    dialogo.current_view = "ai_analysis"
    dialogo.session = {"ai_match_analysis": _registro("match-a", payload)}
    dialogo.refrescado = False
    dialogo.show_ai_analysis = lambda: setattr(dialogo, "refrescado", True)
    capturado = {}

    def mostrar(caja):
        capturado["texto"] = caja.text()
        capturado["detalle"] = caja.detailedText()
        capturado["botones"] = [boton.text() for boton in caja.buttons()]

    monkeypatch.setattr(QMessageBox, "exec", mostrar)
    diagnostico = {
        "http_status": 400,
        "category": "INVALID_ARGUMENT",
        "message": "mimeType application/json rejected",
        "field_path": "generation_config.response_format.text.mime_type",
        "model": "gemini-flash-lite-latest",
    }

    LiveMatchAnalysisDialog._on_ai_analysis_error(
        dialogo, json.dumps(diagnostico, ensure_ascii=False)
    )

    assert dialogo.is_analyzing_ai is False
    assert dialogo.refrescado is True
    assert capturado["texto"] == (
        "Gemini rechazó la configuración del formato de respuesta. "
        "Consulta los detalles del error."
    )
    assert capturado["detalle"] == json.dumps(diagnostico, ensure_ascii=False)
    assert "Cerrar" in capturado["botones"]
    assert dialogo.session["ai_match_analysis"]["model"] == "gemini-flash"
    dialogo.close()
    aplicacion.processEvents()


def test_esquema_no_contiene_tipos_enum_en_mayusculas() -> None:
    def tipos(nodo):
        if isinstance(nodo, dict):
            if "type" in nodo:
                yield nodo["type"]
            for valor in nodo.values():
                yield from tipos(valor)
        elif isinstance(nodo, list):
            for valor in nodo:
                yield from tipos(valor)

    assert set(tipos(ESQUEMA_ANALISIS_GEMINI)) <= {
        "object",
        "string",
        "array",
        "integer",
    }


def test_dashboard_navega_y_selecciona_enfrentamientos(payload: dict) -> None:
    aplicacion = QApplication.instance() or QApplication([])
    registro = _registro("match-a", payload)
    vista = AnalisisPartidaIA(
        {"session_id": "match-a", "champion_name": "Garen"}, registro
    )

    pestanas = vista.findChild(QTabWidget, "matchAnalysisSections")
    botones = vista.findChildren(QPushButton, "matchupChampionButton")
    assert pestanas is not None and pestanas.count() == 6
    assert len(botones) == 5
    botones[2].click()
    assert vista._rival_seleccionado == 2
    assert vista.findChild(QTabWidget, "matchAnalysisSections").count() == 6
    assert vista.isVisible() is False
    assert vista.analisis["farming"]["assessment"] == "Buen ritmo de súbditos."
    assert vista.analisis["itemization"]["alternative_items"] == ["Resistencia mágica"]
    for indice in range(pestanas.count()):
        assert pestanas.widget(indice).findChildren(QFrame, "matchAnalysisCard")
    assert len(vista.analisis["key_enemies"]) == 5
    assert len(vista.analisis["next_game_priorities"]) >= 3
    vista.close()
    aplicacion.processEvents()


def test_resuelve_iconos_o_usa_placeholder_si_faltan_assets(
    monkeypatch, payload: dict
) -> None:
    aplicacion = QApplication.instance() or QApplication([])

    class AssetsAusentes:
        version = "16.20.1"

        def champion_url(self, _nombre):
            raise ValueError("campeón no resuelto")

        def item_url(self, _identificador):
            raise ValueError("objeto no resuelto")

        def set_label_image(self, *_args):
            raise RuntimeError("asset ausente")

    import data_dragon

    monkeypatch.setattr(
        data_dragon, "get_ability_icon_path", lambda *_args, **_kwargs: None
    )

    vista = AnalisisPartidaIA(
        {"session_id": "match-a", "champion_name": "Garen"},
        _registro("match-a", payload),
        assets=AssetsAusentes(),
        item_catalog={"items": {"3006": {"name": "Grebas de berserker"}}},
    )

    assert vista.get_champion_icon("Unknown") is None
    assert vista.get_item_icon("No existe") is None
    assert vista.get_rune_icon("runa inexistente") is None
    assert vista.get_spell_icon("hechizo inexistente") is None
    assert vista.get_ability_icon("Garen", "Q desconocida") is None
    assert vista._icono("champion", "Unknown").text() == "UN"
    assert vista._icono("item", "No existe").text() == "NO"
    vista.close()
    aplicacion.processEvents()
