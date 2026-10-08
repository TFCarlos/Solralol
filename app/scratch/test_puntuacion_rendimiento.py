"""Pruebas del motor de rendimiento, duración, soft cap y premios."""

from itertools import pairwise

from app.services.servicio_puntuacion_rendimiento import (
    REFERENCIAS,
    EntradaRendimientoJugador,
    aplicar_limite_suave,
    clasificar_jugadores,
    multiplicador_duracion,
    puntuacion_categoria,
    puntuar_jugador,
)


def entrada(identificador: str, equipo: str, datos: dict) -> EntradaRendimientoJugador:
    """Crea una entrada de prueba compacta."""
    return EntradaRendimientoJugador(identificador, "Campeón", equipo, "SUPPORT", datos)


def test_referencias_y_limite_suave_sin_tope_total() -> None:
    assert len(REFERENCIAS) == 5
    assert sum(REFERENCIAS.values()) == 1000
    assert aplicar_limite_suave(400, 300) == 350
    assert aplicar_limite_suave(401, 300) == 350
    assert aplicar_limite_suave(7000, 300) == 3650


def test_multiplicador_duracion_en_puntos_control() -> None:
    assert multiplicador_duracion(0) == 3
    assert multiplicador_duracion(900) == 2
    assert float(multiplicador_duracion(1530)) == 1.3
    assert multiplicador_duracion(1800) == 1
    assert float(multiplicador_duracion(2400)) == 0.8
    assert float(multiplicador_duracion(3600)) == 0.5
    assert float(multiplicador_duracion(4000)) == 0.5


def test_ejemplo_combate_280_a_quince_minutos() -> None:
    resultado = puntuacion_categoria(280, 300, 900)
    assert resultado["multiplied"] == 560
    assert resultado["final"] == 430
    jugador = puntuar_jugador(
        entrada(
            "p", "azul", {"kills": 20, "deaths": 0, "assists": 0, "team_kills": 20}
        ),
        900,
    )
    assert jugador["categories"]["combate"]["achievement"] is False
    assert jugador["categories"]["combate"]["achievement_provisional"] is True


def test_normalizacion_permite_superar_referencia_en_partida_larga() -> None:
    resultado = puntuar_jugador(
        entrada(
            "excelente",
            "azul",
            {
                "kills": 20,
                "deaths": 0,
                "assists": 0,
                "team_kills": 20,
                "damage_champions": 100000,
                "team_damage_champions": 100000,
            },
        ),
        1800,
    )
    assert resultado["categories"]["combate"]["final"] > REFERENCIAS["combate"]


def test_orden_duracion_limite_suave_y_truncado() -> None:
    assert puntuacion_categoria(280, 300, 1800)["final"] == 280
    assert puntuacion_categoria(400, 300, 1800)["final"] == 350
    assert puntuacion_categoria(400, 300, 900)["final"] == 550
    assert puntuacion_categoria(301, 300, 1800)["final"] == 300


def test_cada_categoria_aplica_su_limite_suave() -> None:
    finales = [
        puntuacion_categoria(400, referencia, 1800)["final"]
        for referencia in REFERENCIAS.values()
    ]
    assert finales == [350, 275, 325, 275, 275]


def test_curva_duracion_decreciente_y_saturada() -> None:
    muestras = [multiplicador_duracion(segundos) for segundos in range(0, 3601, 30)]
    assert all(actual <= anterior for anterior, actual in pairwise(muestras))
    assert multiplicador_duracion(1529) > multiplicador_duracion(1530)
    assert multiplicador_duracion(1531) < multiplicador_duracion(1530)
    assert multiplicador_duracion(3700) == multiplicador_duracion(3600)


def test_categorias_suman_y_superan_mil() -> None:
    from app.services.servicio_puntuacion_rendimiento import puntuacion_categoria

    categorias = [
        puntuacion_categoria(400, referencia, 900)["final"]
        for referencia in REFERENCIAS.values()
    ]
    assert sum(categorias) > 1000


def test_rangos_compartidos_y_premios_mvp_svp() -> None:
    datos = {
        "kills": 1,
        "deaths": 2,
        "assists": 1,
        "team_kills": 5,
        "cs": 120,
        "gold": 8000,
        "vision": 25,
        "wards_placed": 10,
        "wards_killed": 3,
        "cc_time": 20,
        "healing_allies": 2000,
        "damage_champions": 10000,
        "team_damage_champions": 50000,
        "damage_structures": 1500,
        "damage_taken": 20000,
        "objective_participation": 0.2,
        "structure_contributions": 1,
        "map_pressure": 0.2,
    }
    entradas = [
        entrada(f"p{i}", "perdedor" if i < 5 else "ganador", dict(datos))
        for i in range(10)
    ]
    resultado = clasificar_jugadores(entradas, 1800, "ganador", "postgame")
    assert len(resultado["players"]) == 10
    assert len({p["global_rank"] for p in resultado["players"]}) == 1
    assert all(p["global_rank"] == 1 for p in resultado["players"])
    assert all(
        "MVP" in p["awards"] for p in resultado["players"] if p["team"] == "ganador"
    )
    assert all(
        "MVP/SVP" in p["awards"]
        for p in resultado["players"]
        if p["team"] == "perdedor"
    )
    assert all(p["awards_finalized"] for p in resultado["players"])


def test_soporte_no_se_penaliza_por_menor_cs() -> None:
    soporte = entrada("a", "x", {"cs": 30})
    adc = EntradaRendimientoJugador("b", "Campeón", "x", "BOTTOM", {"cs": 240})
    soporte_score = puntuar_jugador(soporte, 1800)["categories"]["economia"]["final"]
    adc_score = puntuar_jugador(adc, 1800)["categories"]["economia"]["final"]
    assert soporte_score >= adc_score


def test_datos_ausentes_no_confirman_logros() -> None:
    resultado = puntuar_jugador(entrada("p", "azul", {}), 900)
    assert all(
        not categoria["achievement"] for categoria in resultado["categories"].values()
    )
    assert all(
        categoria["completeness"] == 0 for categoria in resultado["categories"].values()
    )


def test_componentes_de_combate_sin_tope_y_participacion_acotada() -> None:
    base = {
        "kills": 12,
        "deaths": 4,
        "assists": 8,
        "team_kills": 30,
        "damage_champions": 28000,
        "team_damage_champions": 140000,
    }
    extra = {**base, "kills": 16, "damage_champions": 40000}
    puntuación_base = puntuar_jugador(entrada("a", "x", base), 1800)["categories"][
        "combate"
    ]
    puntuación_extra = puntuar_jugador(entrada("a", "x", extra), 1800)["categories"][
        "combate"
    ]
    assert (
        puntuación_extra["submetrics"]["bajas_y_asistencias"]
        > puntuación_base["submetrics"]["bajas_y_asistencias"]
    )
    assert (
        puntuación_extra["submetrics"]["dano_campeones"]
        > puntuación_base["submetrics"]["dano_campeones"]
    )
    assert puntuación_extra["submetrics"]["participacion"] <= 110


def test_briar_excepcional_y_soporte_pueden_superar_referencia() -> None:
    briar = EntradaRendimientoJugador(
        "briar",
        "Briar",
        "azul",
        "JUNGLE",
        {
            "kills": 23,
            "deaths": 6,
            "assists": 8,
            "team_kills": 40,
            "damage_champions": 38000,
            "team_damage_champions": 155000,
        },
    )
    soporte = EntradaRendimientoJugador(
        "soporte",
        "Leona",
        "azul",
        "SUPPORT",
        {
            "kills": 2,
            "deaths": 2,
            "assists": 36,
            "team_kills": 38,
            "damage_champions": 21000,
            "team_damage_champions": 150000,
        },
    )
    for participante in (briar, soporte):
        puntuación = puntuar_jugador(participante, 1800)
        assert puntuación["categories"]["combate"]["final"] > 300
    resultado_briar_1800 = puntuar_jugador(briar, 1800)
    resultado_briar = puntuar_jugador(briar, 1960)
    assert (
        resultado_briar["categories"]["combate"]["final"]
        < resultado_briar_1800["categories"]["combate"]["final"]
    )
    ordinario = puntuar_jugador(
        entrada(
            "normal", "x", {"kills": 4, "deaths": 5, "assists": 5, "team_kills": 30}
        ),
        1800,
    )
    assert ordinario["categories"]["combate"]["final"] < 300


def test_estado_pospartida_se_saca_de_sincronizacion_y_victoria_oficial() -> None:
    jugadores = {
        f"p{i}": {
            "team": "blue" if i < 5 else "red",
            "champion_name": "Campeón",
            "role": "TOP",
            "win": i < 5,
        }
        for i in range(10)
    }
    punto = {f"p{i}": {"kills": 2, "deaths": 2, "assists": 3} for i in range(10)}
    sesión = {
        "players": jugadores,
        "snapshots": [{"players": punto}],
        "duration": 1800,
        "postgame": True,
        "final_sync": {"status": "synced"},
    }
    from app.services.servicio_puntuacion_rendimiento import puntuar_sesion

    clasificación = puntuar_sesion(sesión)
    assert clasificación["mode"] == "postgame"
    assert clasificación["awards_finalized"]
    assert clasificación["by_id"]["p0"]["awards"] == ["MVP"]
    assert clasificación["by_id"]["p5"]["awards"] == ["MVP/SVP"]


def test_lider_perdedor_en_rango_global_tercero_recibe_svp() -> None:
    valores = [30, 25, 5, 4, 3, 20, 2, 1, 1, 1]
    entradas = [
        EntradaRendimientoJugador(
            f"p{i}",
            "Campeón",
            "blue" if i < 5 else "red",
            "MID",
            {"kills": bajas, "deaths": 2, "assists": 3, "team_kills": 100},
        )
        for i, bajas in enumerate(valores)
    ]
    resultado = clasificar_jugadores(entradas, 1800, "blue", "postgame")
    assert resultado["by_id"]["p5"]["global_rank"] == 3
    assert resultado["by_id"]["p5"]["awards"] == ["SVP"]
    assert resultado["by_id"]["p0"]["awards"] == ["MVP"]


def test_log_guardado_incluye_clasificacion_final() -> None:
    from app.services.match_log_service import MatchLogService

    puntuación = {"state": "POSTGAME_FINAL", "awards_finalized": True, "players": []}
    servicio = MatchLogService.__new__(MatchLogService)
    registro = servicio.build_match_log(
        {"session_id": "fixture", "players": {}, "performance_scoring": puntuación}
    )
    assert registro["performance_scoring"] == puntuación


def test_equipo_ganador_desconocido_no_cierra_premios() -> None:
    jugadores = {
        f"p{i}": {
            "team": "blue" if i < 5 else "red",
            "champion_name": "Campeón",
            "role": "TOP",
            "win": None,
        }
        for i in range(10)
    }
    puntos = {f"p{i}": {"kills": 2, "deaths": 2, "assists": 3} for i in range(10)}
    sesión = {
        "players": jugadores,
        "snapshots": [{"players": puntos}],
        "duration": 1800,
        "winning_team": "DESCONOCIDO",
        "postgame": True,
        "final_sync": {"status": "synced"},
    }
    from app.services.servicio_puntuacion_rendimiento import puntuar_sesion

    clasificación = puntuar_sesion(sesión)
    assert not clasificación["awards_finalized"]
    assert all(not jugador["awards"] for jugador in clasificación["players"])


def test_kda_incompleto_deja_clasificacion_pospartida_pendiente() -> None:
    jugadores = {
        f"p{i}": {
            "team": "blue" if i < 5 else "red",
            "champion_name": "Campeón",
            "role": "TOP",
            "win": i < 5,
        }
        for i in range(10)
    }
    puntos = {f"p{i}": {"kills": 2, "deaths": 2, "assists": 3} for i in range(10)}
    del puntos["p4"]["deaths"]
    sesión = {
        "players": jugadores,
        "snapshots": [{"players": puntos}],
        "duration": 1800,
        "winning_team": "blue",
        "postgame": True,
        "final_sync": {"status": "synced"},
    }
    from app.services.servicio_puntuacion_rendimiento import puntuar_sesion

    clasificación = puntuar_sesion(sesión)
    assert clasificación["finalization_state"] == "POSTGAME_PENDING"
    assert not clasificación["awards_finalized"]
    assert all(not jugador["awards"] for jugador in clasificación["players"])
