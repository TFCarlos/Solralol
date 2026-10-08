"""Pruebas de integración del diálogo LIVE y su timeline frente a versus."""

import os
from typing import Any
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget

from app.services.live_event_participation import (
    classify_event_participation,
    filter_participating_events,
)
from app.services.live_match_tracker import LiveMatchTracker
from app.ui.desglose_rendimiento_dialogo import DialogoDesgloseRendimiento
from app.ui.live_match_analysis_dialog import HighlightFlow, LiveMatchAnalysisDialog
from app.ui.live_timeline import TimelineModel, TimelineView


class RecursosPrueba(QWidget):
    """Proporciona los contratos de recursos sin red ni archivos externos."""

    image_ready = Signal(str, QPixmap)
    version = "16.17.1"

    def champion_url(self, nombre: str) -> str:
        """Devuelve una URL vacía para usar el fallback de retrato."""
        return ""

    def item_url(self, identificador: int) -> str:
        """Devuelve una URL vacía para usar el fallback de objeto."""
        return ""

    def request_pixmap(self, url: str, key: str) -> QPixmap:
        """Devuelve un mapa de píxeles vacío sin consultar recursos externos."""
        return QPixmap()

    def set_label_image(self, label: QWidget, *args: object, **kwargs: object) -> None:
        """Mantiene el label sin iniciar descargas durante la prueba."""


@pytest.fixture
def aplicacion_qt() -> QApplication:
    """Crea la aplicación Qt offscreen compartida por estas pruebas."""
    return QApplication.instance() or QApplication([])


def crear_sesion() -> dict[str, Any]:
    """Crea una pareja de jugadores y eventos representativos de partida."""
    jugadores = {
        "left": {
            "champion_name": "Briar",
            "riot_id": "Left#EUW",
            "role": "TOP",
            "runes": {},
        },
        "right": {
            "champion_name": "Nidalee",
            "riot_id": "Right#EUW",
            "role": "TOP",
            "runes": {},
        },
        "other": {
            "champion_name": "Lux",
            "riot_id": "Other#EUW",
            "role": "MID",
            "runes": {},
        },
    }
    puntos = {
        key: {
            "level": 12,
            "kills": 4,
            "deaths": 2,
            "assists": 6,
            "cs": 100,
            "stats": {},
        }
        for key in jugadores
    }
    eventos = [
        {
            "type": "item_purchase",
            "item_id": 1001,
            "player_key": "left",
            "time": 10,
            "label": "Compra: Botas",
        },
        {
            "type": "item_purchase",
            "item_id": 2003,
            "player_key": "right",
            "time": 20,
            "label": "Compra: Poción",
        },
        {
            "type": "kill_exact",
            "player_key": "left",
            "killer_key": "left",
            "victim_key": "other",
            "time": 30,
            "label": "Briar eliminó a Lux",
        },
        {
            "type": "kill_exact",
            "player_key": "right",
            "killer_key": "right",
            "victim_key": "left",
            "time": 40,
            "label": "Nidalee eliminó a Briar",
        },
        {
            "type": "death_exact",
            "player_key": "left",
            "killer_key": "right",
            "victim_key": "left",
            "time": 45,
            "label": "Briar murió ante Nidalee",
        },
        {
            "type": "death_exact",
            "player_key": "right",
            "killer_key": "left",
            "victim_key": "right",
            "time": 48,
            "label": "Nidalee murió ante Briar",
        },
        {
            "type": "objective",
            "player_key": "other",
            "scope": "global",
            "time": 50,
            "label": "Dragón abatido",
        },
        {
            "type": "kill_exact",
            "player_key": "other",
            "killer_key": "other",
            "victim_key": "left",
            "time": 60,
            "label": "Lux eliminó a Briar",
        },
        {
            "type": "kill_exact",
            "player_key": "other",
            "killer_key": "other",
            "victim_key": "other",
            "time": 61,
            "label": "Lux eliminó a Lux",
        },
        {"type": "item_undo", "item_id": 0, "player_key": "left", "time": 70},
        {"type": "item_purchase", "item_id": 0, "player_key": "left", "time": 71},
    ]
    matchups = {
        role: {"ally_key": "left", "enemy_key": "right"}
        for role in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY")
    }
    return {
        "champion_name": "Briar",
        "game_mode": "CLASSIC",
        "players": jugadores,
        "lane_matchups": matchups,
        "snapshots": [{"time": 90, "players": puntos}],
        "events": eventos,
        "achievements": {"left": [], "right": []},
    }


def test_timeline_asigna_lados_por_jugador_y_filtra_item_cero(
    aplicacion_qt: QApplication,
) -> None:
    """Asigna cada evento a su actor seleccionado o al centro neutral."""
    sesion = crear_sesion()
    modelo = TimelineModel(
        {"items": {"1001": {"name_es": "Botas"}, "2003": {"name_es": "Poción"}}}
    )
    modelo.set_events(sesion["events"], "left", "right", sesion["players"])

    filas = [
        modelo.data(modelo.index(index), TimelineModel.EventRole)
        for index in range(modelo.rowCount())
    ]

    assert [fila["side"] for fila in filas] == [
        "left",
        "right",
        "left",
        "direct",
        "direct",
        "direct",
        "center",
        "left",
        "neutral",
        "left",
    ]
    assert filas[0]["item_id"] == "1001"
    assert filas[-1]["text"] == "Deshizo una compra"
    assert all("Objeto 0" not in fila["text"] for fila in filas)
    assert filas[2]["killer_champion"] == "Briar"
    assert filas[2]["victim_champion"] == "Lux"
    assert filas[3]["category"] == "DIRECT_RIGHT_KILLS_LEFT"
    assert filas[4]["category"] == "DIRECT_RIGHT_KILLS_LEFT"
    assert filas[5]["category"] == "DIRECT_LEFT_KILLS_RIGHT"


def test_highlight_flow_es_widget_insertable_y_envuelve(
    aplicacion_qt: QApplication,
) -> None:
    """Inserta hasta diez badges como widget y los redistribuye al estrecharse."""
    from PySide6.QtWidgets import QLabel, QVBoxLayout

    contenedor = QWidget()
    layout = QVBoxLayout(contenedor)
    flow = HighlightFlow(contenedor)
    layout.addWidget(flow)
    flow.resize(150, 240)
    for index in range(10):
        flow.add_badge(QLabel(f"Destacado {index} con texto largo"))

    posiciones = [flow.layout().getItemPosition(index) for index in range(10)]

    assert layout.itemAt(0).widget() is flow
    assert flow.layout().count() == 10
    assert max(posicion[0] for posicion in posiciones) > 0


def test_dialogo_construye_columnas_cambia_roles_y_actualiza_estadisticas(
    aplicacion_qt: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Construye los tres paneles, conmuta cinco roles y procesa refresh async."""
    import main

    monkeypatch.setattr(LiveMatchAnalysisDialog, "_prepare_session", Mock())
    dialogo = LiveMatchAnalysisDialog(crear_sesion(), RecursosPrueba(), {"items": {}})
    assert main.main is not None
    dialogo.show()
    for role in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"):
        dialogo.show_role(role)
        aplicacion_qt.processEvents()
        assert not dialogo.grab().isNull()
        pagina = dialogo._role_pages[role]["widget"]
        cuerpo = pagina.layout()
        izquierda = cuerpo.itemAt(0).widget()
        derecha = cuerpo.itemAt(2).widget()
        assert isinstance(izquierda, QScrollArea)
        assert cuerpo.itemAt(1).widget().objectName() == "liveTimelinePanel"
        assert isinstance(derecha, QScrollArea)
        assert izquierda.widget().objectName() == "livePlayerPanel"
        assert derecha.widget().objectName() == "livePlayerPanel"
        assert izquierda.widget().layout().count() == 7
        assert derecha.widget().layout().count() == 7
        assert dialogo._role_pages[role]["timeline"].timeline_model.rowCount() > 0
        if role == "TOP":
            dialogo._change_timeline_mode("global")
            fila_global = dialogo.timeline_view.timeline_model.data(
                dialogo.timeline_view.timeline_model.index(0), TimelineModel.EventRole
            )
            assert fila_global["side"] == "center"
            dialogo._change_timeline_mode("all")
    dialogo._stats_ready(
        dialogo._revision,
        ({"left": ["Victoria"], "right": []}, {"left": {}, "right": {}}),
        None,
    )
    assert dialogo.current_role == "UTILITY"
    assert dialogo._role_pages["UTILITY"]["widget"].layout().count() == 3
    dialogo._refresh_timer.stop()
    dialogo.close()


def test_premio_final_actualiza_tarjeta_y_desglose_con_la_misma_identidad(
    aplicacion_qt: QApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refresca puesto y cuenta cuando una sincronización reemplaza LIVE por final."""
    import app.ui.live_match_analysis_dialog as live_module
    from app.services.servicio_puntuacion_rendimiento import (
        EntradaRendimientoJugador,
        puntuar_jugador,
    )

    monkeypatch.setattr(LiveMatchAnalysisDialog, "_prepare_session", Mock())
    sesión = crear_sesion()
    sesión["players"]["left"].update(
        {
            "riot_id": "chaos:marqq#black",
            "riot_id_game_name": "Marqq",
            "riot_id_tagline": "BLACK",
        }
    )
    diálogo = LiveMatchAnalysisDialog(sesión, RecursosPrueba(), {"items": {}})
    resultado_final = puntuar_jugador(
        EntradaRendimientoJugador(
            "left",
            "Briar",
            "blue",
            "TOP",
            {
                "kills": 10,
                "deaths": 2,
                "assists": 8,
                "team_kills": 25,
                "damage_champions": 25000,
                "team_damage_champions": 100000,
            },
        ),
        1800,
        "postgame",
    )
    resultado_final.update(
        {
            "total": 757,
            "global_rank": 1,
            "team_rank": 1,
            "awards": ["MVP"],
            "awards_finalized": True,
            "finalization_state": "POSTGAME_FINAL",
            "riot_id": "Marqq#BLACK",
        }
    )
    resultado_live = dict(
        resultado_final,
        awards=[],
        awards_finalized=False,
        finalization_state="LIVE_PROVISIONAL",
    )
    calcular = Mock(
        side_effect=[
            {"by_id": {"left": resultado_live}},
            {"by_id": {"left": resultado_final}},
        ]
    )
    monkeypatch.setattr(live_module, "puntuar_sesion", calcular)
    diálogo._performance_cache_signature = None

    assert diálogo._player_match_rank("left") == "757p · LÍDER PROVISIONAL"
    diálogo.session["final_sync"] = {"status": "synced"}
    diálogo.session["final_scoreboard"] = {"left": {"kills": 10, "win": True}}
    assert diálogo._player_match_rank("left") == "757p · 1º · MVP"
    resultado_final.update(global_rank=3, team_rank=1, awards=["SVP"])
    assert diálogo._player_match_rank("left") == "757p · 3º · SVP"
    resultado_final.update(global_rank=1, awards=["MVP/SVP"])
    assert diálogo._player_match_rank("left") == "757p · 1º · MVP/SVP"
    cabecera = diálogo._create_player_header(
        diálogo.session["players"]["left"], "left", "ally"
    )
    assert cabecera.findChild(QLabel, "livePlayerName").text() == "Marqq#BLACK"
    desglose = DialogoDesgloseRendimiento(resultado_final)
    assert desglose.findChild(QLabel, "performanceChampionName").text() == "Briar"
    assert desglose.findChild(QLabel, "performancePlayerName").text() == "Marqq#BLACK"
    assert desglose.findChild(QLabel, "performanceAwardValue").text() == "MVP/SVP"
    actualizado = dict(resultado_final, total=920, awards=["MVP/SVP"])
    desglose.actualizar_resultado(actualizado)
    assert desglose.findChild(QLabel, "performanceTotal").text() == "920 PUNTOS"
    assert desglose.findChild(QLabel, "performanceAwardValue").text() == "MVP/SVP"
    assert calcular.call_count == 2
    diálogo._refresh_timer.stop()
    diálogo.close()


@pytest.mark.parametrize("cantidad", [0, 1, 6, 10])
def test_panel_de_destacados_acepta_cero_y_varios_badges(
    aplicacion_qt: QApplication, monkeypatch: pytest.MonkeyPatch, cantidad: int
) -> None:
    """Construye el panel vacío o con varios logros sin error de layouts."""
    monkeypatch.setattr(LiveMatchAnalysisDialog, "_prepare_session", Mock())
    sesion = crear_sesion()
    sesion["achievements"]["left"] = [f"Destacado {index}" for index in range(cantidad)]
    dialogo = LiveMatchAnalysisDialog(sesion, RecursosPrueba(), {"items": {}})
    panel = dialogo._create_awards_panel("left", "ally")

    assert isinstance(panel, QWidget)
    if cantidad:
        flow = panel.layout().itemAt(1).widget()
        assert isinstance(flow, HighlightFlow)
        assert flow.layout().count() == min(cantidad, 6)
    else:
        assert panel.layout().itemAt(1).widget().text() == "Sin logros detectados aún"
    dialogo._refresh_timer.stop()
    dialogo.close()


def test_timeline_empareja_direct_kill_y_deduplica_perspectivas(
    aplicacion_qt: QApplication,
) -> None:
    """Agrupa kill/death del mismo evento y conserva asesinatos cercanos."""
    modelo = TimelineModel({"items": {}})
    jugadores = {"l": {"champion_name": "Yone"}, "r": {"champion_name": "Illaoi"}}
    eventos = [
        {
            "type": "kill_exact",
            "event_id": "native:1",
            "killer_key": "l",
            "victim_key": "r",
            "time": 340,
            "time_label": "05:40",
        },
        {
            "type": "death_exact",
            "event_id": "native:1",
            "killer_key": "l",
            "victim_key": "r",
            "time": 340,
            "time_label": "05:40",
        },
        {
            "type": "kill_exact",
            "event_id": "native:2",
            "killer_key": "r",
            "victim_key": "l",
            "time": 342,
            "time_label": "05:42",
        },
        {
            "type": "death_exact",
            "event_id": "native:2",
            "killer_key": "r",
            "victim_key": "l",
            "time": 342,
            "time_label": "05:42",
        },
        {
            "type": "death_exact",
            "event_id": "native:3",
            "killer_key": "x",
            "victim_key": "l",
            "time": 500,
            "time_label": "08:20",
        },
        {
            "type": "kill_exact",
            "event_id": "native:4",
            "killer_key": "l",
            "victim_key": "x",
            "time": 501,
            "time_label": "08:21",
        },
    ]
    modelo.set_events(eventos, "l", "r", jugadores)
    filas = [
        modelo.data(modelo.index(i), TimelineModel.EventRole)
        for i in range(modelo.rowCount())
    ]
    assert len(filas) == 4
    assert [row["category"] for row in filas] == [
        "DIRECT_LEFT_KILLS_RIGHT",
        "DIRECT_RIGHT_KILLS_LEFT",
        "LEFT_DEATH",
        "LEFT_KILL",
    ]
    assert filas[0]["victim_text"] == "Illaoi murió"
    assert filas[0]["killer_text"] == "Yone eliminó a Illaoi"
    assert filas[1]["timestamp"] == "05:42"
    assert filas[2]["text"] == "Yone murió"
    assert filas[2]["side"] == "left"


def test_timeline_renderiza_asistente_en_su_lado_y_asistencia_directa_como_fila_compartida(
    aplicacion_qt: QApplication,
) -> None:
    """Muestra la asistencia propia y la muerte del rival en una fila sincronizada."""
    modelo = TimelineModel({"items": {}})
    players = {
        "left": {"champion_name": "Briar"},
        "right": {"champion_name": "Diana"},
        "third": {"champion_name": "Darius"},
        "target": {"champion_name": "Thresh"},
    }
    events = [
        {
            "type": "kill_exact",
            "event_id": "assist-external",
            "killer_key": "third",
            "victim_key": "target",
            "assister_keys": ["left"],
            "assist_data_complete": True,
            "time": 12,
        },
        {
            "type": "kill_exact",
            "event_id": "assist-direct",
            "killer_key": "third",
            "victim_key": "right",
            "assister_keys": ["left"],
            "assist_data_complete": True,
            "time": 21,
        },
    ]
    modelo.set_events(events, "left", "right", players)
    rows = [
        modelo.data(modelo.index(index), TimelineModel.EventRole)
        for index in range(modelo.rowCount())
    ]
    assert len(rows) == 2
    assert rows[0]["category"] == "LEFT_ASSIST"
    assert rows[0]["side"] == "left"
    assert "Briar asistió" in rows[0]["text"]
    assert "Darius eliminó a Thresh" in rows[0]["text"]
    assert rows[1]["category"] == "SHARED_ASSIST_PARTICIPATION"
    assert rows[1]["side"] == "direct"
    assert rows[1]["left_involvement"] == "ASSIST"
    assert rows[1]["right_involvement"] == "DEATH"
    assert rows[1]["right_text"] == "Diana murió"
    view = TimelineView({"items": {}}, RecursosPrueba())
    view.set_events(events, "left", "right", players)
    view.resize(720, 320)
    view.show()
    aplicacion_qt.processEvents()
    assert not view.grab().isNull()
    view.close()


def test_badges_tienen_ancho_natural_y_no_separan_los_chips(
    aplicacion_qt: QApplication,
) -> None:
    """Conserva frases de logro legibles y agrupadas como chips completos."""
    from PySide6.QtWidgets import QLabel

    flow = HighlightFlow()
    for text in ("Ha ganado el early", "Armadura"):
        flow.add_badge(QLabel(text))
    flow.resize(360, flow.heightForWidth(360))
    flow.show()
    aplicacion_qt.processEvents()
    first, second = flow.findChildren(QLabel)
    assert first.width() >= 104
    assert second.x() < first.x() + first.width() + 12
    assert first.text() == "Ha ganado el early"
    assert first.height() >= 32


def test_tracker_deduplica_eventos_nativos_y_preserva_kills_cercanos() -> None:
    """Identifica eventos por ID o timestamp preciso sin colapsar kills distintos."""
    tracker = LiveMatchTracker({}, persist=False)
    tracker.session = {
        "players": {
            "left": {
                "champion_name": "Yone",
                "riot_id": "Yone#EUW",
                "summoner_name": "Yone",
            },
            "right": {
                "champion_name": "Illaoi",
                "riot_id": "Illaoi#EUW",
                "summoner_name": "Illaoi",
            },
        },
        "seen_event_ids": [],
        "events": [],
        "player_timelines": {},
        "match_id": 42,
    }
    evento = {
        "EventID": 7,
        "EventName": "ChampionKill",
        "EventTime": 340.0,
        "KillerName": "Yone",
        "VictimName": "Illaoi",
    }
    tracker._record_exact_events({"game_events": [evento]})
    tracker._record_exact_events({"game_events": [evento]})
    assert len(tracker.session["events"]) == 2
    assert {entry["event_id"] for entry in tracker.session["events"]} == {"native:7"}
    sin_id = {key: value for key, value in evento.items() if key != "EventID"}
    sin_id["EventTime"] = 340.4
    tracker._record_exact_events({"game_events": [sin_id]})
    assert len(tracker.session["events"]) == 4
    sin_id_a = dict(sin_id, VictimName="Illaoi", EventTime=342.0, EventID=0)
    sin_id_b = dict(sin_id, VictimName="Illaoi", EventTime=342.1, EventID=0)
    tracker._record_exact_events({"game_events": [sin_id_a, sin_id_b]})
    assert len(tracker.session["events"]) == 8


def test_filtro_linea_solo_incluye_participantes_y_asistencias_confirmadas() -> None:
    """Excluye kills ajenas y asigna asistencias por ID del participante."""
    eventos = [
        {
            "type": "kill_exact",
            "event_id": "a",
            "killer_key": "darius",
            "victim_key": "yasuo",
            "time": 3,
        },
        {
            "type": "kill_exact",
            "event_id": "b",
            "killer_key": "darius",
            "victim_key": "yasuo",
            "assister_keys": ["diana"],
            "assist_data_complete": True,
            "time": 4,
        },
        {
            "type": "kill_exact",
            "event_id": "c",
            "killer_key": "darius",
            "victim_key": "thresh",
            "assister_keys": ["briar"],
            "assist_data_complete": True,
            "time": 5,
        },
        {
            "type": "kill_exact",
            "event_id": "d",
            "killer_key": "briar",
            "victim_key": "thresh",
            "time": 6,
        },
        {
            "type": "kill_exact",
            "event_id": "e",
            "killer_key": "diana",
            "victim_key": "thresh",
            "time": 7,
        },
        {
            "type": "death_exact",
            "event_id": "f",
            "killer_key": "enemy",
            "victim_key": "briar",
            "time": 8,
        },
        {
            "type": "death_exact",
            "event_id": "g",
            "killer_key": "ally",
            "victim_key": "diana",
            "time": 9,
        },
        {
            "type": "kill_exact",
            "event_id": "h",
            "killer_key": "briar",
            "victim_key": "diana",
            "time": 10,
        },
        {
            "type": "kill_exact",
            "event_id": "i",
            "killer_key": "diana",
            "victim_key": "briar",
            "time": 11,
        },
        {
            "type": "kill_exact",
            "event_id": "j",
            "killer_key": "darius",
            "victim_key": "diana",
            "assister_keys": ["briar"],
            "assist_data_complete": True,
            "time": 12,
        },
        {
            "type": "kill_exact",
            "event_id": "k",
            "killer_key": "other",
            "victim_key": "other",
            "time": 13,
        },
    ]
    filtered = filter_participating_events(eventos, "lane", "briar", "diana")
    assert [event["event_id"] for event in filtered] == list("bcdefghij")
    roles = [
        classify_event_participation(event, "briar", "diana") for event in filtered
    ]
    assert [(role.left, role.right) for role in roles] == [
        ("NONE", "ASSIST"),
        ("ASSIST", "NONE"),
        ("KILL", "NONE"),
        ("NONE", "KILL"),
        ("DEATH", "NONE"),
        ("NONE", "DEATH"),
        ("KILL", "DEATH"),
        ("DEATH", "KILL"),
        ("ASSIST", "DEATH"),
    ]
    assert all(role.shared for role in roles[-3:])


def test_asistencia_ausente_no_crea_participacion_y_rol_recalcula() -> None:
    """Marca asistentes desconocidos y recalcula la misma baja para otro duelo."""
    event = {
        "type": "kill_exact",
        "killer_key": "darius",
        "victim_key": "yasuo",
        "time": 10,
    }
    role = classify_event_participation(event, "briar", "diana")
    assert role.left == role.right == "NONE"
    assert role.participation_complete is False
    assert filter_participating_events([event], "lane", "briar", "diana") == []
    changed = filter_participating_events([event], "lane", "darius", "yasuo")
    assert changed == [event]


def test_global_filter_solo_muestra_objetivos_y_union_ordenada() -> None:
    """Mantiene objetivos globales fuera del feed de bajas ajenas."""
    events = [
        {
            "type": "kill_exact",
            "event_id": "kill",
            "killer_key": "x",
            "victim_key": "y",
            "time": 20,
        },
        {"type": "objective", "event_id": "dragon", "time": 30},
        {"type": "item_purchase", "event_id": "item", "player_key": "left", "time": 10},
        {"type": "objective", "event_id": "dragon", "time": 30},
    ]
    assert [
        event.get("event_id")
        for event in filter_participating_events(events, "global", "left", "right")
    ] == ["dragon"]
    assert [
        event.get("event_id")
        for event in filter_participating_events(events, "all", "left", "right")
    ] == ["item", "dragon"]


def test_tracker_resuelve_alias_exactos_y_asistentes_por_participant_id() -> None:
    """Evita confundir campeones o nombres parecidos y valida el equipo asistente."""
    tracker = LiveMatchTracker({}, persist=False)
    tracker.session = {
        "players": {
            "blue:participant:1": {
                "participant_id": 1,
                "riot_id": "Diana#EUW",
                "summoner_name": "DianaMain",
                "champion_name": "Diana",
                "team": "ORDER",
            },
            "red:participant:2": {
                "participant_id": 2,
                "riot_id": "Diana#NA1",
                "summoner_name": "Diana",
                "champion_name": "Briar",
                "team": "CHAOS",
            },
        }
    }
    assert tracker._key_from_identity("1") == "blue:participant:1"
    assert tracker._key_from_identity("DianaMain") == "blue:participant:1"
    assert tracker._key_from_identity("Dian") is None
    assert tracker._key_from_identity("Briar") is None
    event = {"KillerName": "DianaMain", "Assisters": [2]}
    assistants, complete = tracker._assists_from_event(event)
    assert assistants == []
    assert complete is False
