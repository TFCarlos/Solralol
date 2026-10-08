"""Regresiones de calibracion v3 y disponibilidad del postgame."""

import json
from typing import Any

from app.services.match_log_service import MatchLogService
from app.services.postgame_sync_service import PostgameSyncService
from app.services.servicio_puntuacion_rendimiento import (
    NOMBRES_METRICAS,
    REFERENCIAS,
    VERSION_PUNTUACION,
    EntradaRendimientoJugador,
    puntuar_jugador,
    puntuar_sesion,
)


def test_referencias_v4_y_pesos_de_combate_y_objetivos() -> None:
    """Comprueba version y referencias redistribuidas sin alterar categorias."""
    assert VERSION_PUNTUACION == 4
    assert REFERENCIAS == {
        "combate": 300,
        "economia": 150,
        "objetivos": 250,
        "vision": 150,
        "supervivencia": 150,
    }
    datos = {
        "kills": 12,
        "assists": 10,
        "deaths": 3,
        "team_kills": 25,
        "damage_champions": 18000,
        "team_damage_champions": 120000,
        "objective_participation": 1,
        "structure_contributions": 3,
        "damage_structures": 9000,
        "map_pressure": 1,
    }
    categorias = puntuar_jugador(
        EntradaRendimientoJugador("p", "Campeon", "azul", "MID", datos), 1800
    )["categories"]
    assert categorias["combate"]["submetrics"]["participacion"] == 96.8
    assert categorias["combate"]["submetrics"]["bajas_y_asistencias"] > 45
    assert categorias["combate"]["submetrics"]["dano_campeones"] < 50
    assert categorias["objetivos"]["submetrics"]["participacion_objetivos"] == 45
    assert categorias["objetivos"]["submetrics"]["torres_inhibidores"] == 30
    assert categorias["objetivos"]["submetrics"]["dano_estructuras"] == 70
    assert categorias["objetivos"]["unavailable_metrics"] == ["dano_objetivos"]


def test_damage_a_objetivos_se_puntua_desde_el_campo_generico() -> None:
    """Mantiene no disponible el daño épico cuando el participante no lo aporta."""
    score = puntuar_jugador(
        EntradaRendimientoJugador(
            "jungla",
            "Campeon",
            "azul",
            "JUNGLE",
            {
                "kills": 5,
                "assists": 10,
                "deaths": 3,
                "team_kills": 20,
                "damage_objectives": 50000,
            },
        ),
        1800,
        "postgame",
    )
    objetivos = score["categories"]["objetivos"]
    assert objetivos["submetrics"]["dano_objetivos"] > 0
    assert NOMBRES_METRICAS["dano_objetivos"] == "Daño a objetivos"
    dano_objetivos_verificado = puntuar_jugador(
        EntradaRendimientoJugador(
            "contribuidor",
            "Campeon",
            "azul",
            "MID",
            {"damage_objectives": 9000, "objective_participation": 0},
        ),
        1800,
    )["categories"]["objetivos"]
    assert dano_objetivos_verificado["submetrics"]["dano_objetivos"] == 75
    assert dano_objetivos_verificado["submetrics"]["participacion_objetivos"] == 0


def test_dano_real_a_torres_pesa_mas_que_el_ultimo_golpe() -> None:
    """Compara daño medido a estructuras con una baja de torre aislada."""
    con_dano = puntuar_jugador(
        EntradaRendimientoJugador(
            "empuje",
            "Campeon",
            "azul",
            "TOP",
            {
                "damage_structures": 9000,
                "structure_contributions": 0,
                "objective_participation": 0,
                "map_pressure": 0,
            },
        ),
        1800,
    )["categories"]["objetivos"]
    solo_ultimo_golpe = puntuar_jugador(
        EntradaRendimientoJugador(
            "remate",
            "Campeon",
            "azul",
            "TOP",
            {
                "damage_structures": 0,
                "structure_contributions": 1,
                "objective_participation": 0,
                "map_pressure": 0,
            },
        ),
        1800,
    )["categories"]["objetivos"]
    assert con_dano["submetrics"]["dano_estructuras"] == 70
    assert solo_ultimo_golpe["submetrics"]["torres_inhibidores"] == 10
    assert con_dano["raw"] > solo_ultimo_golpe["raw"]


def test_participante_sin_datos_utility_no_recibe_ceros_fabricados() -> None:
    """Deja ausentes las métricas no presentes y conserva ceros explicitos."""
    servicio = PostgameSyncService.__new__(PostgameSyncService)
    incompleto = servicio._official_player_stats({"kills": 1})
    cero_confirmado = servicio._official_player_stats(
        {"totalTimeCrowdControlDealt": 0, "totalHeal": 0}
    )
    assert incompleto["total_time_crowd_control_dealt"] is None
    assert incompleto["total_heal"] is None
    assert incompleto["total_damage_shielded_on_teammates"] is None
    assert cero_confirmado["total_time_crowd_control_dealt"] == 0
    assert cero_confirmado["total_heal"] == 0


def test_combate_equilibra_asesino_soporte_carry_y_muertes() -> None:
    """Compara arquetipos con entradas de partida sin favorecer campeones."""

    def puntuar(rol: str, datos: dict[str, int]) -> dict[str, Any]:
        """Calcula las categorias para un perfil de rol de prueba."""
        return puntuar_jugador(
            EntradaRendimientoJugador(rol, "Campeon", "azul", rol, datos), 1800
        )["categories"]["combate"]

    base = {"team_kills": 30, "team_damage_champions": 150000}
    asesino = puntuar(
        "MID",
        {
            **base,
            "kills": 15,
            "assists": 6,
            "deaths": 2,
            "damage_champions": 30000,
        },
    )
    carry = puntuar(
        "BOTTOM",
        {
            **base,
            "kills": 5,
            "assists": 5,
            "deaths": 2,
            "damage_champions": 90000,
        },
    )
    apoyo = puntuar(
        "SUPPORT",
        {
            **base,
            "kills": 2,
            "assists": 29,
            "deaths": 4,
            "damage_champions": 15000,
        },
    )
    asesino_muchas_muertes = puntuar(
        "MID",
        {
            **base,
            "kills": 15,
            "assists": 6,
            "deaths": 15,
            "damage_champions": 30000,
        },
    )
    assert asesino["raw"] > carry["raw"]
    assert apoyo["submetrics"]["participacion"] == 110
    assert (
        asesino_muchas_muertes["submetrics"]["eficiencia_combate"]
        < asesino["submetrics"]["eficiencia_combate"]
    )


def test_fuente_postgame_alimenta_cc_curacion_escudo_y_autosustento() -> None:
    """Comprueba extraccion oficial y su puntuacion separada en utility."""
    servicio = PostgameSyncService.__new__(PostgameSyncService)
    oficial = servicio._official_player_stats(
        {
            "totalTimeCrowdControlDealt": 24,
            "totalHeal": 14000,
            "totalHealsOnTeammates": 8000,
            "totalDamageShieldedOnTeammates": 2400,
        }
    )
    roster = {
        "p": {
            "team": "azul",
            "champion_name": "Campeon",
            "role": "SUPPORT",
        }
    }
    sesion = {
        "players": roster,
        "snapshots": [{"players": {"p": {"stats": {}}}}],
        "final_scoreboard": {"p": oficial},
        "duration": 1800,
    }
    resultado = puntuar_sesion(sesion, "postgame")["by_id"]["p"]
    métricas = resultado["categories"]["vision"]["submetrics"]
    assert métricas["control_masas"] > 0
    assert métricas["curacion_aliados"] > 0
    assert métricas["escudos_aliados"] > 0
    assert "autosustento" in métricas
    assert métricas["autosustento"] < métricas["curacion_aliados"]


def test_log_guardado_persiste_fuentes_crudas_y_no_fabrica_epic_damage() -> None:
    """Conserva las fuentes Match-V5 en el resumen guardado para recalcular."""
    servicio_sync = PostgameSyncService.__new__(PostgameSyncService)
    final = servicio_sync._official_player_stats(
        {
            "damageDealtToTurrets": 9000,
            "totalTimeCCDealt": 14,
            "totalHeal": 4000,
            "totalHealsOnTeammates": 1500,
            "totalDamageShieldedOnTeammates": 700,
        }
    )
    servicio_log = MatchLogService.__new__(MatchLogService)
    log = servicio_log.build_match_log(
        {
            "session_id": "match-fixture",
            "champion_name": "Campeon",
            "duration": 1800,
            "local_player_key": "p",
            "local_team": "blue",
            "winning_team": "blue",
            "players": {
                "p": {
                    "champion_name": "Campeon",
                    "role": "MID",
                    "team": "blue",
                    "win": True,
                    "riot_id": "Cuenta#TAG",
                }
            },
            "final_scoreboard": {"p": final},
        }
    )
    jugador = log["all_players"][0]
    assert jugador["damage_dealt_to_turrets"] == 9000
    assert jugador["total_time_crowd_control_dealt"] == 14
    assert jugador["total_heal"] == 4000
    assert jugador["total_heals_on_teammates"] == 1500
    assert jugador["total_damage_shielded_on_teammates"] == 700
    assert jugador["damage_dealt_to_objectives"] is None


def test_cero_cc_confirmado_se_puntua_como_cero_y_cambia_version() -> None:
    """Confirma que CC medido cero existe y queda marcado como calibracion 3."""
    categoria = puntuar_jugador(
        EntradaRendimientoJugador("p", "Campeon", "azul", "TOP", {"cc_time": 0}),
        1800,
    )["categories"]["vision"]
    assert categoria["submetrics"]["control_masas"] == 0
    assert categoria["unavailable_metrics"]


def test_match_v5_damage_de_objetivos_alimenta_submetrica() -> None:
    """Conserva el campo genérico y deja el daño épico no disponible."""
    servicio = PostgameSyncService.__new__(PostgameSyncService)
    participante = servicio._official_player_stats(
        {"damageDealtToObjectives": 18200, "neutralMinionsKilled": 94}
    )
    assert participante["damage_dealt_to_objectives"] == 18200
    assert participante["epic_monster_damage"] is None


def test_dano_objetivos_normalizado_distingue_cero_de_ausencia() -> None:
    """Puntúa cero medido y marca como no disponible el dato ausente."""
    cero = puntuar_jugador(
        EntradaRendimientoJugador(
            "cero", "Campeon", "azul", "SUPPORT", {"damage_objectives": 0}
        ),
        1800,
        "postgame",
    )["categories"]["objetivos"]
    ausente = puntuar_jugador(
        EntradaRendimientoJugador("ausente", "Campeon", "azul", "MID", {}),
        1800,
        "postgame",
    )["categories"]["objetivos"]
    assert cero["submetrics"]["dano_objetivos"] == 0
    assert "dano_objetivos" not in cero["unavailable_metrics"]
    assert "dano_objetivos" in ausente["unavailable_metrics"]


def test_log_serializado_conserva_dano_objetivos_disponible_y_diagnostico() -> None:
    """Retiene el valor canonico ya medido al serializar el Saved Match."""
    servicio = MatchLogService.__new__(MatchLogService)
    registro = servicio.build_match_log(
        {
            "session_id": "fixture-epic",
            "duration": 1800,
            "local_player_key": "p",
            "players": {
                "p": {
                    "champion_name": "Campeon",
                    "role": "JUNGLE",
                    "team": "blue",
                    "final": {"damage_dealt_to_objectives": 1234},
                }
            },
            "epic_damage_diagnostics": {
                "match_id": "EUW1_123",
                "provider": "fixture",
                "persistence_retained": None,
            },
        }
    )
    restaurado = json.loads(json.dumps(registro))
    assert restaurado["all_players"][0]["damage_dealt_to_objectives"] == 1234
    assert restaurado["metadata"]["epic_damage_diagnostics"]["persistence_retained"]


def test_puntuacion_recibe_dano_objetivos_y_recalcula_puntos_y_rango() -> None:
    """Recalcula la puntuacion y el rango al incorporar una medicion fiable."""
    jugadores = {
        "p": {"team": "blue", "champion_name": "Campeon", "role": "JUNGLE"},
        "q": {"team": "red", "champion_name": "Campeon", "role": "TOP"},
    }
    base = {
        "players": jugadores,
        "duration": 1800,
        "winning_team": "blue",
        "postgame": True,
        "final_scoreboard": {
            "p": {
                "damage_dealt_to_objectives": 0,
                "kills": 0,
                "deaths": 2,
                "assists": 0,
            },
            "q": {
                "damage_dealt_to_objectives": 0,
                "kills": 0,
                "deaths": 2,
                "assists": 0,
            },
        },
    }
    antes = puntuar_sesion(base, "postgame")["by_id"]["p"]
    base["final_scoreboard"]["p"]["damage_dealt_to_objectives"] = 9000
    despues = puntuar_sesion(base, "postgame")["by_id"]["p"]
    assert despues["categories"]["objetivos"]["submetrics"]["dano_objetivos"] == 75
    assert despues["total"] > antes["total"]
    assert despues["global_rank"] == 1
