"""Pruebas de puntuacion defensiva, persistencia y desglose grafico."""

import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from app.services.match_log_service import MatchLogService
from app.services.postgame_sync_service import PostgameSyncService
from app.services.servicio_puntuacion_rendimiento import (
    DISTRIBUCION_SUPERVIVENCIA,
    VERSION_PUNTUACION,
    EntradaRendimientoJugador,
    puntuar_jugador,
    puntuar_sesion,
)
from app.ui.desglose_rendimiento_dialogo import DialogoDesgloseRendimiento


def _resultado(
    datos: dict[str, int | float | None], rol: str = "SUPPORT"
) -> dict[str, Any]:
    """Puntua una entrada defensiva aislada con datos controlados."""
    return puntuar_jugador(
        EntradaRendimientoJugador("p", "Braum", "blue", rol, datos), 1800, "postgame"
    )


def test_dano_util_recibido_100000_con_70_por_ciento_suma_70_puntos() -> None:
    """Aplica exactamente un punto por cada mil de daño ponderado."""
    resultado = _resultado(
        {
            "kills": 7,
            "assists": 0,
            "team_kills": 10,
            "deaths": 0,
            "damage_taken": 100_000,
        }
    )
    supervivencia = resultado["categories"]["supervivencia"]
    assert supervivencia["submetrics"]["dano_util_recibido"] == 70
    assert supervivencia["defensive_metrics"]["kill_participation"] == 0.7
    assert supervivencia["defensive_metrics"]["useful_damage_taken"] == 70_000


def test_dano_mitigado_util_80000_con_70_por_ciento_suma_28_puntos() -> None:
    """Aplica un punto por cada dos mil de mitigacion ponderada."""
    resultado = _resultado(
        {
            "kills": 7,
            "assists": 0,
            "team_kills": 10,
            "deaths": 0,
            "damage_self_mitigated": 80_000,
        }
    )
    supervivencia = resultado["categories"]["supervivencia"]
    assert supervivencia["submetrics"]["dano_mitigado_util"] == 28
    assert supervivencia["defensive_metrics"]["useful_mitigated_damage"] == 56_000


def test_participacion_se_acota_y_cero_no_premia_dano_recibido() -> None:
    """Limita la participacion a uno y da cero puntos si no hubo bajas o asistencias."""
    excedido = _resultado(
        {"kills": 12, "assists": 2, "team_kills": 10, "damage_taken": 100_000}
    )
    cero = _resultado(
        {
            "kills": 0,
            "assists": 0,
            "team_kills": 10,
            "damage_taken": 100_000,
            "damage_self_mitigated": 80_000,
        }
    )
    assert (
        excedido["categories"]["supervivencia"]["defensive_metrics"][
            "kill_participation"
        ]
        == 1
    )
    assert (
        excedido["categories"]["supervivencia"]["submetrics"]["dano_util_recibido"]
        == 100
    )
    assert cero["categories"]["supervivencia"]["submetrics"]["dano_util_recibido"] == 0
    assert cero["categories"]["supervivencia"]["submetrics"]["dano_mitigado_util"] == 0


def test_datos_defensivos_ausentes_no_se_convierten_en_ceros() -> None:
    """Deja no disponible participacion y defensa cuando faltan sus fuentes."""
    resultado = _resultado({"kills": 2, "assists": 1, "deaths": 2})
    supervivencia = resultado["categories"]["supervivencia"]
    metricas = supervivencia["defensive_metrics"]
    assert metricas["kill_participation"] is None
    assert metricas["damage_taken"] is None
    assert metricas["damage_self_mitigated"] is None
    assert "dano_util_recibido" in supervivencia["unavailable_metrics"]
    assert "dano_mitigado_util" in supervivencia["unavailable_metrics"]


def test_cero_defensivo_medido_es_distinto_de_dato_ausente() -> None:
    """Conserva cero como observacion y muestra ausencias por separado."""
    resultado = _resultado(
        {
            "kills": 0,
            "assists": 0,
            "team_kills": 0,
            "deaths": 0,
            "damage_taken": 0,
            "damage_self_mitigated": 0,
        }
    )
    supervivencia = resultado["categories"]["supervivencia"]
    assert supervivencia["submetrics"]["dano_util_recibido"] == 0
    assert supervivencia["submetrics"]["dano_mitigado_util"] == 0
    assert "dano_util_recibido" not in supervivencia["unavailable_metrics"]


def test_dano_recibido_y_mitigado_se_mantienen_separados() -> None:
    """Suma contribuciones distintas y conserva las dos fuentes originales."""
    resultado = _resultado(
        {
            "kills": 7,
            "assists": 0,
            "team_kills": 10,
            "deaths": 0,
            "damage_taken": 100_000,
            "damage_self_mitigated": 80_000,
        }
    )
    supervivencia = resultado["categories"]["supervivencia"]
    metricas = supervivencia["defensive_metrics"]
    assert metricas["damage_taken"] == 100_000
    assert metricas["damage_self_mitigated"] == 80_000
    assert metricas["useful_damage_taken_points"] == 70
    assert metricas["useful_mitigated_damage_points"] == 28
    assert supervivencia["raw"] == 162.5


def test_mas_muertes_reducen_eficiencia_y_no_crean_puntos_defensivos() -> None:
    """Comprueba que recibir dano sin participacion no recompensa las muertes."""
    eficaz = _resultado(
        {
            "kills": 0,
            "assists": 0,
            "team_kills": 10,
            "deaths": 1,
            "damage_taken": 100_000,
        }
    )
    alimentado = _resultado(
        {
            "kills": 0,
            "assists": 0,
            "team_kills": 10,
            "deaths": 15,
            "damage_taken": 100_000,
        }
    )
    eficaz_supervivencia = eficaz["categories"]["supervivencia"]
    alimentado_supervivencia = alimentado["categories"]["supervivencia"]
    assert eficaz_supervivencia["submetrics"]["dano_util_recibido"] == 0
    assert alimentado_supervivencia["submetrics"]["dano_util_recibido"] == 0
    assert (
        alimentado_supervivencia["submetrics"]["eficiencia_muertes"]
        < eficaz_supervivencia["submetrics"]["eficiencia_muertes"]
    )


def test_distribucion_supervivencia_suma_150_y_version_es_nueva() -> None:
    """Verifica la referencia defensiva propuesta y la version del modelo."""
    assert sum(DISTRIBUCION_SUPERVIVENCIA.values()) == 150
    assert VERSION_PUNTUACION == 4


def test_misma_contribucion_defensiva_no_depende_del_rol() -> None:
    """Aplica la misma formula a frontline y backline sin bonus de campeon."""
    datos = {
        "kills": 7,
        "assists": 0,
        "team_kills": 10,
        "deaths": 0,
        "damage_taken": 100_000,
        "damage_self_mitigated": 80_000,
    }
    tanque = _resultado(datos, "TOP")["categories"]["supervivencia"]
    carry = _resultado(datos, "BOTTOM")["categories"]["supervivencia"]
    assert tanque["raw"] == carry["raw"]
    assert tanque["submetrics"] == carry["submetrics"]


def test_multiplicador_se_aplica_una_vez_antes_del_soft_cap() -> None:
    """Mantiene puntos de submetricas crudos y aplica duracion y soft-cap al total."""
    datos = {
        "kills": 7,
        "assists": 0,
        "team_kills": 10,
        "deaths": 0,
        "damage_taken": 100_000,
        "damage_self_mitigated": 80_000,
    }
    treinta = _resultado(datos)
    veinticinco = puntuar_jugador(
        EntradaRendimientoJugador("p", "Braum", "blue", "SUPPORT", datos),
        1530,
        "postgame",
    )
    assert treinta["multiplicador_duracion"] == 1
    assert veinticinco["multiplicador_duracion"] == 1.3
    assert veinticinco["categories"]["supervivencia"]["raw"] == 162.5
    assert veinticinco["categories"]["supervivencia"]["multiplied"] == 211
    assert veinticinco["categories"]["supervivencia"]["final"] == 180


def test_postgame_extrae_dano_taken_y_mitigacion_sin_fabricar_ceros() -> None:
    """Normaliza Match-V5 y distingue ceros, valores medidos y campos ausentes."""
    servicio = PostgameSyncService.__new__(PostgameSyncService)
    medido = servicio._official_player_stats(
        {"totalDamageTaken": 100_000, "damageSelfMitigated": 80_000}
    )
    cero = servicio._official_player_stats(
        {"totalDamageTaken": 0, "damageSelfMitigated": 0}
    )
    ausente = servicio._official_player_stats({"kills": 1})
    assert medido["damage_taken"] == 100_000
    assert medido["damage_self_mitigated"] == 80_000
    assert cero["damage_taken"] == 0
    assert cero["damage_self_mitigated"] == 0
    assert ausente["damage_taken"] is None
    assert ausente["damage_self_mitigated"] is None


def test_team_kills_incompletos_hacen_no_disponible_la_participacion() -> None:
    """No infiere total de bajas cuando falta el dato de un jugador del equipo."""
    jugadores = {
        "a": {"team": "blue", "champion_name": "Braum", "role": "SUPPORT"},
        "b": {"team": "blue", "champion_name": "Caitlyn", "role": "BOTTOM"},
    }
    resultado = puntuar_sesion(
        {
            "players": jugadores,
            "duration": 1800,
            "snapshots": [{"players": {"a": {"kills": 2, "assists": 1}}}],
            "final_scoreboard": {"a": {"damage_taken": 100_000}},
        }
    )["by_id"]["a"]
    supervivencia = resultado["categories"]["supervivencia"]
    assert supervivencia["defensive_metrics"]["team_kills"] is None
    assert supervivencia["defensive_metrics"]["kill_participation"] is None
    assert "dano_util_recibido" in supervivencia["unavailable_metrics"]


def test_participacion_usa_solo_las_bajas_del_equipo_propio() -> None:
    """No divide las bajas del jugador entre los kills de ambos equipos."""
    jugadores = {
        "a": {"team": "blue", "champion_name": "Braum", "role": "SUPPORT"},
        "b": {"team": "blue", "champion_name": "Campeon", "role": "TOP"},
        "c": {"team": "red", "champion_name": "Campeon", "role": "TOP"},
        "d": {"team": "red", "champion_name": "Campeon", "role": "TOP"},
    }
    marcador = {
        "a": {"kills": 2, "assists": 0, "deaths": 0, "damage_taken": 10_000},
        "b": {"kills": 0, "assists": 0, "deaths": 0},
        "c": {"kills": 8, "assists": 0, "deaths": 0},
        "d": {"kills": 0, "assists": 0, "deaths": 0},
    }
    resultado = puntuar_sesion(
        {"players": jugadores, "final_scoreboard": marcador, "duration": 1800}
    )["by_id"]["a"]
    metricas = resultado["categories"]["supervivencia"]["defensive_metrics"]
    assert metricas["team_kills"] == 2
    assert metricas["kill_participation"] == 1


def test_final_postgame_reemplaza_snapshot_live_defensivo() -> None:
    """Prefiere dano y mitigacion oficiales finales a una instantanea anterior."""
    jugadores = {
        "a": {"team": "blue", "champion_name": "Braum", "role": "SUPPORT"},
        "b": {"team": "blue", "champion_name": "Campeon", "role": "TOP"},
    }
    resultado = puntuar_sesion(
        {
            "players": jugadores,
            "duration": 1800,
            "postgame": True,
            "snapshots": [
                {
                    "players": {
                        "a": {
                            "kills": 2,
                            "assists": 0,
                            "deaths": 0,
                            "damage_taken": 900_000,
                            "damage_self_mitigated": 900_000,
                        },
                        "b": {"kills": 0, "assists": 0, "deaths": 0},
                    }
                }
            ],
            "final_scoreboard": {
                "a": {"damage_taken": 100_000, "damage_self_mitigated": 80_000},
                "b": {"kills": 0, "assists": 0, "deaths": 0},
            },
        }
    )["by_id"]["a"]["categories"]["supervivencia"]["defensive_metrics"]
    assert resultado["damage_taken"] == 100_000
    assert resultado["damage_self_mitigated"] == 80_000
    assert resultado["useful_damage_taken_points"] == 100
    assert resultado["useful_mitigated_damage_points"] == 40


def test_ranking_y_premios_se_recalculan_con_datos_defensivos_postgame() -> None:
    """Actualiza lider, MVP y SVP desde el resultado defensivo final."""
    jugadores = {}
    marcador = {}
    for indice in range(10):
        equipo = "blue" if indice < 5 else "red"
        clave = f"p{indice}"
        jugadores[clave] = {
            "team": equipo,
            "champion_name": "Braum" if indice == 0 else "Campeon",
            "role": "SUPPORT" if indice == 0 else "TOP",
        }
        marcador[clave] = {
            "kills": 2 if indice in (0, 5) else 0,
            "deaths": 1,
            "assists": 0,
            "damage_taken": 100_000 if indice == 0 else 0,
            "damage_self_mitigated": 80_000 if indice == 0 else 0,
            "gold_earned": 10_000,
            "vision_score": 20,
            "total_damage_dealt_to_champions": 10_000,
        }
    resultado = puntuar_sesion(
        {
            "players": jugadores,
            "duration": 1800,
            "postgame": True,
            "winning_team": "blue",
            "final_scoreboard": marcador,
        },
        "postgame",
    )
    assert resultado["by_id"]["p0"]["global_rank"] == 1
    assert "MVP" in resultado["by_id"]["p0"]["awards"]
    assert resultado["by_id"]["p5"]["awards_finalized"]
    assert "SVP" in resultado["by_id"]["p5"]["awards"]
    assert resultado["version"] == 4


def test_saved_match_persiste_estadisticas_y_score_defensivos(tmp_path: Path) -> None:
    """Serializa metricas defensivas y el resultado versionado del jugador."""
    servicio_puntuacion = _resultado(
        {
            "kills": 7,
            "assists": 0,
            "team_kills": 10,
            "deaths": 0,
            "damage_taken": 100_000,
            "damage_self_mitigated": 80_000,
        }
    )
    servicio_log = MatchLogService.__new__(MatchLogService)
    guardado = servicio_log.build_match_log(
        {
            "session_id": "defensive-fixture",
            "duration": 1800,
            "local_player_key": "p",
            "local_team": "blue",
            "winning_team": "blue",
            "players": {
                "p": {
                    "champion_name": "Braum",
                    "role": "SUPPORT",
                    "team": "blue",
                    "win": True,
                }
            },
            "final_scoreboard": {
                "p": {
                    "kills": 7,
                    "deaths": 0,
                    "assists": 0,
                    "damage_taken": 100_000,
                    "damage_self_mitigated": 80_000,
                }
            },
            "performance_scoring": {
                "version": 4,
                "players": [servicio_puntuacion],
            },
        }
    )
    ruta = tmp_path / "match.json"
    ruta.write_text(json.dumps(guardado), encoding="utf-8")
    restaurado = json.loads(ruta.read_text(encoding="utf-8"))
    assert restaurado["all_players"][0]["damage_taken"] == 100_000
    assert restaurado["all_players"][0]["damage_self_mitigated"] == 80_000
    assert restaurado["performance_scoring"]["version"] == 4
    assert (
        restaurado["performance_scoring"]["players"][0]["categories"]["supervivencia"][
            "defensive_metrics"
        ]["kill_participation"]
        == 0.7
    )


def test_sesion_guardada_v3_se_recalcula_con_modelo_v4() -> None:
    """Recalcula una sesion guardada cuando conserva las fuentes finales."""
    sesion = {
        "players": {
            "a": {"team": "blue", "champion_name": "Braum", "role": "SUPPORT"},
            "b": {"team": "blue", "champion_name": "Campeon", "role": "TOP"},
        },
        "duration": 1800,
        "postgame": True,
        "performance_scoring": {"version": 3},
        "final_scoreboard": {
            "a": {
                "kills": 1,
                "assists": 0,
                "deaths": 0,
                "damage_taken": 150_000,
                "damage_self_mitigated": 80_000,
            },
            "b": {"kills": 1, "assists": 0, "deaths": 0},
        },
    }
    actual = puntuar_sesion(sesion, "postgame")
    assert actual["version"] == 4
    assert (
        actual["by_id"]["a"]["categories"]["supervivencia"]["submetrics"][
            "dano_util_recibido"
        ]
        == 75
    )


def test_desglose_grafico_muestra_aportes_defensivos_y_datos_crudos() -> None:
    """Renderiza puntos defensivos, participacion, datos y estado ausente en Qt."""
    aplicacion = QApplication.instance() or QApplication([])
    resultado = _resultado(
        {
            "kills": 7,
            "assists": 0,
            "team_kills": 10,
            "deaths": 0,
            "damage_taken": 100_000,
            "damage_self_mitigated": 80_000,
        }
    )
    dialogo = DialogoDesgloseRendimiento(resultado)
    dialogo.botones_detalle["supervivencia"].click()
    aplicacion.processEvents()
    textos = [
        etiqueta.text()
        for etiqueta in dialogo.detalles["supervivencia"].findChildren(QLabel)
    ]
    assert "Daño útil recibido" in textos
    assert "Daño mitigado útil" in textos
    assert "100,000" in textos
    assert "70.0%" in textos
    assert "80,000" in textos
    assert "×1.00" in textos
    assert "Puntuación final" in textos
    nombres = {
        etiqueta.text(): etiqueta
        for etiqueta in dialogo.detalles["supervivencia"].findChildren(QLabel)
    }
    assert (
        nombres["Daño útil recibido"].toolTip()
        == "Estimación del daño recibido ponderada por tu participación en las eliminaciones del equipo."
    )
    assert (
        nombres["Daño mitigado útil"]
        .toolTip()
        .startswith(
            "Daño mitigado registrado, ponderado por tu participación en las eliminaciones."
        )
    )
    dialogo.close()
    aplicacion.processEvents()


def test_desglose_gui_muestra_no_disponible_y_cero_defensivo() -> None:
    """Distingue estadisticas defensivas ausentes y ceros en el dialogo."""
    aplicacion = QApplication.instance() or QApplication([])
    incompleto = _resultado({"kills": 0, "assists": 0, "deaths": 0})
    dialogo_incompleto = DialogoDesgloseRendimiento(incompleto)
    dialogo_incompleto.botones_detalle["supervivencia"].click()
    aplicacion.processEvents()
    valores_incompletos = [
        etiqueta.text()
        for etiqueta in dialogo_incompleto.detalles["supervivencia"].findChildren(
            QLabel, "performanceMetricValue"
        )
    ]
    assert valores_incompletos.count("No disponible") >= 2
    dialogo_incompleto.close()
    cero = _resultado(
        {
            "kills": 0,
            "assists": 0,
            "team_kills": 0,
            "deaths": 0,
            "damage_taken": 0,
            "damage_self_mitigated": 0,
        }
    )
    dialogo_cero = DialogoDesgloseRendimiento(cero)
    dialogo_cero.botones_detalle["supervivencia"].click()
    aplicacion.processEvents()
    valores_cero = [
        etiqueta.text()
        for etiqueta in dialogo_cero.detalles["supervivencia"].findChildren(
            QLabel, "performanceMetricValue"
        )
    ]
    assert valores_cero.count("0.0 p") >= 2
    dialogo_cero.close()
