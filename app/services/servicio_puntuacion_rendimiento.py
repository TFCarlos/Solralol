"""Puntuación común, determinista y explicable del rendimiento de jugadores."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from itertools import pairwise
from typing import Any

from app.services.identidad_jugador import nombre_riot_visible

VERSION_PUNTUACION = 4
REFERENCIAS = {
    "combate": 300,
    "economia": 150,
    "objetivos": 250,
    "vision": 150,
    "supervivencia": 150,
}
DISTRIBUCION_SUPERVIVENCIA = {
    "eficiencia_muertes": 40,
    "impacto_en_lucha": 35,
    "dano_util_recibido": 45,
    "dano_mitigado_util": 30,
}
TITULOS_CATEGORIA = {
    "combate": "Combate y participación",
    "economia": "Economía y eficiencia",
    "objetivos": "Objetivos y presión",
    "vision": "Visión y utilidad",
    "supervivencia": "Supervivencia e impacto",
}
NOMBRES_LOGRO = {
    "combate": "Maestro del combate",
    "economia": "Dominio económico",
    "objetivos": "Conquistador de objetivos",
    "vision": "Visión excepcional",
    "supervivencia": "Inquebrantable",
}
PUNTOS_DURACION = (
    (0, Decimal(3)),
    (900, Decimal(2)),
    (1800, Decimal(1)),
    (2400, Decimal("0.8")),
    (3600, Decimal("0.5")),
)
ROLES = {
    "TOP": "top",
    "JUNGLE": "jungla",
    "JUNG": "jungla",
    "MIDDLE": "medio",
    "MID": "medio",
    "BOTTOM": "tirador",
    "BOT": "tirador",
    "UTILITY": "apoyo",
    "SUPPORT": "apoyo",
    "SUP": "apoyo",
}
NOMBRES_METRICAS = {
    "participacion": "Participación en bajas del equipo",
    "bajas_y_asistencias": "Bajas y asistencias",
    "dano_campeones": "Daño a campeones",
    "eficiencia_combate": "Eficiencia de combate",
    "oro_por_minuto": "Oro por minuto",
    "eficiencia_cs": "Eficiencia de súbditos",
    "eficiencia_economica": "Eficiencia económica",
    "participacion_objetivos": "Participación confirmada en objetivos",
    "torres_inhibidores": "Torres e inhibidores destruidos",
    "dano_estructuras": "Daño a estructuras",
    "dano_objetivos": "Daño a objetivos",
    "presion_mapa": "Presión de mapa (proxy de daño a objetivos)",
    "vision": "Puntuación de visión",
    "control_vision": "Control de visión",
    "control_masas": "Control de masas aplicado",
    "curacion_aliados": "Curación a aliados",
    "escudos_aliados": "Escudos a aliados",
    "autosustento": "Autosustento medido",
    "eficiencia_muertes": "Eficiencia de muertes",
    "dano_util_recibido": "Daño útil recibido",
    "dano_mitigado_util": "Daño mitigado útil",
    "impacto_en_lucha": "Impacto en combates",
}
FUENTES_METRICAS = {
    "dano_estructuras": "Match-V5 info.participants[].damageDealtToTurrets; guardado en final_scoreboard.damage_dealt_to_turrets.",
    "dano_objetivos": "Match-V5 info.participants[].damageDealtToObjectives; daño genérico a objetivos, no exclusivo de monstruos épicos. Se normaliza por minuto con referencia 300.",
    "bajas_y_asistencias": "(bajas + asistencias) por minuto / 1,2; referencia 110 y retornos decrecientes.",
    "dano_campeones": "Daño individual / daño total del equipo, normalizado por la referencia de rol; referencia 50.",
    "eficiencia_combate": "(bajas + asistencias) / (1 + muertes por cada tres minutos) / 3; referencia 30.",
    "torres_inhibidores": "Bajas oficiales de torres e inhibidores; referencia 30 con base de tres contribuciones.",
    "control_masas": "Match-V5 info.participants[].totalTimeCCDealt; acepta totalTimeCrowdControlDealt y timeCCingOthers como alias.",
    "curacion_aliados": "Match-V5 info.participants[].totalHealsOnTeammates.",
    "escudos_aliados": "Match-V5 info.participants[].totalDamageShieldedOnTeammates.",
    "autosustento": "Diferencia entre totalHeal y totalHealsOnTeammates, solo cuando ambos campos están presentes.",
    "presion_mapa": "Proxy de presión de mapa calculado con damageDealtToObjectives / 10 000, limitado a 1.",
    "dano_util_recibido": "Estimación del daño recibido ponderada por tu participación en las eliminaciones del equipo.",
    "dano_mitigado_util": "Daño mitigado registrado, ponderado por tu participación en las eliminaciones. Match-V5 usa damageSelfMitigated; no garantiza incluir proyectiles bloqueados para aliados.",
}


@dataclass(frozen=True)
class EntradaRendimientoJugador:
    """Estadísticas observadas para puntuar un participante."""

    id_participante: str
    campeon: str
    equipo: str
    rol: str
    estadisticas: dict[str, Any]


def aplicar_limite_suave(puntos: int, referencia: int) -> int:
    """Reduce el excedente al 50 %; recibe puntos y referencia, devuelve un entero."""
    if referencia < 0:
        raise ValueError("La referencia no puede ser negativa")
    return puntos if puntos <= referencia else referencia + (puntos - referencia) // 2


def multiplicador_duracion(duracion_segundos: int) -> Decimal:
    """Interpola por segundos de partida y devuelve el factor Decimal continuo."""
    duracion = max(0, int(duracion_segundos))
    for (inicio, valor_inicio), (fin, valor_fin) in pairwise(PUNTOS_DURACION):
        if inicio <= duracion <= fin:
            progreso = Decimal(duracion - inicio) / Decimal(fin - inicio)
            return valor_inicio + (valor_fin - valor_inicio) * progreso
    return Decimal("0.5")


def puntuacion_categoria(
    bruto: Decimal | float, referencia: int, duracion_segundos: int
) -> dict[str, Any]:
    """Calcula etapas desde puntos, referencia y segundos; devuelve el desglose."""
    puntos_brutos = Decimal(str(bruto))
    multiplicador = multiplicador_duracion(duracion_segundos)
    multiplicado = int(
        (puntos_brutos * multiplicador).to_integral_value(rounding=ROUND_DOWN)
    )
    final = aplicar_limite_suave(multiplicado, referencia)
    return {
        "raw": float(puntos_brutos),
        "multiplied": multiplicado,
        "reference": referencia,
        "excess": max(0, multiplicado - referencia),
        "excess_reduction": max(0, multiplicado - referencia) // 2,
        "final": final,
    }


def _numero(datos: dict[str, Any], clave: str) -> Decimal | None:
    """Lee datos por clave y devuelve un Decimal no negativo o None si no sirven."""
    valor = datos.get(clave)
    if valor is None:
        return None
    try:
        return max(Decimal(0), Decimal(str(valor)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _componente(
    datos: dict[str, Any], clave: str, referencia: Decimal, techo: Decimal
) -> Decimal | None:
    """Normaliza datos por clave, referencia y techo; devuelve puntos o None."""
    valor = _numero(datos, clave)
    if valor is None:
        return None
    return _puntos_con_retornos(valor / techo, referencia)


def _puntos_con_retornos(proporcion: Decimal, referencia: Decimal) -> Decimal:
    """Convierte una proporción y referencia en puntos con retornos decrecientes."""
    proporcion = max(Decimal(0), proporcion)
    if proporcion <= 1:
        return referencia * proporcion
    return referencia * (Decimal(1) + (proporcion - 1).sqrt())


def _normaliza_rol(rol: str) -> str:
    """Agrupa un rol recibido y devuelve su etiqueta normalizada."""
    return ROLES.get(str(rol or "").upper(), "desconocido")


def puntuar_jugador(
    entrada: EntradaRendimientoJugador, duracion_segundos: int, modo: str = "live"
) -> dict[str, Any]:
    """Puntúa entrada, duración y modo; devuelve categorías, logros y completitud."""
    datos = entrada.estadisticas
    duracion = max(1, duracion_segundos)
    minutos = Decimal(duracion) / Decimal(60)
    rol = _normaliza_rol(entrada.rol)
    asesinatos, muertes, asistencias = (
        _numero(datos, campo) for campo in ("kills", "deaths", "assists")
    )
    kills_equipo = _numero(datos, "team_kills")
    cs = _numero(datos, "cs")
    oro = _numero(datos, "earned_gold") or _numero(datos, "gold")
    dano = _numero(datos, "damage_champions")
    dano_equipo = _numero(datos, "team_damage_champions")
    participacion = (
        None
        if kills_equipo is None or asesinatos is None or asistencias is None
        else Decimal(0)
        if kills_equipo == 0
        else max(
            Decimal(0),
            min(Decimal(1), (asesinatos + asistencias) / kills_equipo),
        )
    )
    cs_techo = {
        "apoyo": Decimal(1),
        "jungla": Decimal(7),
        "tirador": Decimal(10),
        "top": Decimal(9),
        "medio": Decimal(9),
    }.get(rol, Decimal(8))
    oro_techo = Decimal(600 if rol == "apoyo" else 900)
    proporcion_dano_referencia = {
        "apoyo": Decimal("0.12"),
        "jungla": Decimal("0.20"),
        "top": Decimal("0.20"),
        "medio": Decimal("0.22"),
        "tirador": Decimal("0.25"),
    }.get(rol, Decimal("0.20"))
    contrib_combate = {
        "participacion": _puntos_con_retornos((participacion or 0), Decimal(110))
        if participacion is not None
        else None,
        "bajas_y_asistencias": _puntos_con_retornos(
            ((asesinatos or 0) + (asistencias or 0)) / minutos / Decimal("1.2"),
            Decimal(110),
        )
        if asesinatos is not None and asistencias is not None
        else None,
        "dano_campeones": _puntos_con_retornos(
            ((dano / dano_equipo) / proporcion_dano_referencia)
            if dano is not None and dano_equipo and dano_equipo > 0
            else ((dano / minutos / Decimal(500)) / proporcion_dano_referencia)
            if dano is not None
            else Decimal(0),
            Decimal(50),
        )
        if dano is not None
        else None,
        "eficiencia_combate": _puntos_con_retornos(
            (
                ((asesinatos or 0) + (asistencias or 0))
                / (Decimal(1) + (muertes or 0) / max(Decimal(1), minutos / Decimal(3)))
            )
            / Decimal(3),
            Decimal(30),
        )
        if all(x is not None for x in (asesinatos, asistencias, muertes))
        else None,
    }
    contrib_economia = {
        "oro_por_minuto": _componente(
            {"v": oro / minutos if oro is not None else None},
            "v",
            Decimal(60),
            oro_techo,
        ),
        "eficiencia_cs": _componente(
            {"v": cs / minutos if cs is not None else None}, "v", Decimal(40), cs_techo
        ),
        "eficiencia_economica": min(
            Decimal(75),
            (oro / minutos / _numero(datos, "team_gold_average_per_minute"))
            / Decimal("1.25")
            * 50,
        )
        if oro is not None
        and _numero(datos, "team_gold_average_per_minute")
        and _numero(datos, "team_gold_average_per_minute") > 0
        else None,
    }
    contrib_objetivos = {
        "participacion_objetivos": _componente(
            datos, "objective_participation", Decimal(45), Decimal(1)
        ),
        "torres_inhibidores": _componente(
            datos, "structure_contributions", Decimal(30), Decimal(3)
        ),
        "dano_estructuras": _componente(
            {
                "v": _numero(datos, "damage_structures") / minutos
                if _numero(datos, "damage_structures") is not None
                else None
            },
            "v",
            Decimal(70),
            Decimal(300),
        ),
        "dano_objetivos": _componente(
            {
                "v": _numero(datos, "damage_objectives") / minutos
                if _numero(datos, "damage_objectives") is not None
                else None
            },
            "v",
            Decimal(75),
            Decimal(300),
        ),
        "presion_mapa": _componente(datos, "map_pressure", Decimal(30), Decimal(1)),
    }
    contrib_vision = {
        "vision": _componente(datos, "vision", Decimal(60), max(Decimal(1), minutos)),
        "control_vision": min(
            Decimal(45),
            (
                (_numero(datos, "wards_placed") or 0)
                + (_numero(datos, "wards_killed") or 0) * Decimal("1.5")
            )
            / minutos
            * 5,
        )
        if _numero(datos, "wards_placed") is not None
        or _numero(datos, "wards_killed") is not None
        else None,
        "control_masas": _componente(
            {
                "v": _numero(datos, "cc_time") / minutos
                if _numero(datos, "cc_time") is not None
                else None
            },
            "v",
            Decimal(30),
            Decimal(12),
        ),
        "curacion_aliados": _componente(
            {"v": (_numero(datos, "healing_allies") or 0) / minutos},
            "v",
            Decimal(20 if rol == "apoyo" else 15),
            Decimal(500),
        )
        if _numero(datos, "healing_allies") is not None
        else None,
        "escudos_aliados": _componente(
            {"v": (_numero(datos, "shielding_allies") or 0) / minutos},
            "v",
            Decimal(7 if rol == "apoyo" else 5),
            Decimal(300),
        )
        if _numero(datos, "shielding_allies") is not None
        else None,
        "autosustento": _componente(
            {"v": (_numero(datos, "self_healing") or 0) / minutos},
            "v",
            Decimal(3 if rol == "apoyo" else 10),
            Decimal(700),
        )
        if _numero(datos, "self_healing") is not None
        else None,
    }
    deaths_eficientes = (
        Decimal(DISTRIBUCION_SUPERVIVENCIA["eficiencia_muertes"])
        / (Decimal(1) + (muertes or 0) / max(Decimal(1), minutos / 3))
        if muertes is not None
        else None
    )
    dano_recibido = _numero(datos, "damage_taken")
    dano_mitigado = _numero(datos, "damage_self_mitigated")
    dano_util = (
        dano_recibido * participacion
        if dano_recibido is not None and participacion is not None
        else None
    )
    dano_mitigado_util = (
        dano_mitigado * participacion
        if dano_mitigado is not None and participacion is not None
        else None
    )
    puntos_dano_util = (
        int(dano_util // Decimal(1000)) if dano_util is not None else None
    )
    puntos_dano_mitigado = (
        int(dano_mitigado_util // Decimal(2000))
        if dano_mitigado_util is not None
        else None
    )
    impacto_en_lucha = (
        participacion * Decimal(DISTRIBUCION_SUPERVIVENCIA["impacto_en_lucha"])
        if participacion is not None
        else None
    )
    supervivencia = {
        "eficiencia_muertes": deaths_eficientes,
        "impacto_en_lucha": impacto_en_lucha,
        "dano_util_recibido": Decimal(puntos_dano_util)
        if puntos_dano_util is not None
        else None,
        "dano_mitigado_util": Decimal(puntos_dano_mitigado)
        if puntos_dano_mitigado is not None
        else None,
    }
    grupos = {
        "combate": contrib_combate,
        "economia": contrib_economia,
        "objetivos": contrib_objetivos,
        "vision": contrib_vision,
        "supervivencia": supervivencia,
    }
    multiplicador = multiplicador_duracion(duracion_segundos)
    categorias: dict[str, Any] = {}
    for categoria, partes in grupos.items():
        disponibles = {
            nombre: valor for nombre, valor in partes.items() if valor is not None
        }
        bruto = sum(disponibles.values(), Decimal(0))
        referencia = REFERENCIAS[categoria]
        etapas = puntuacion_categoria(bruto, referencia, duracion_segundos)
        final = etapas["final"]
        umbral_alcanzado = final >= referencia and bool(disponibles)
        logro_confirmado = (
            umbral_alcanzado and len(disponibles) == len(partes) and modo == "postgame"
        )
        categorias[categoria] = {
            **etapas,
            "submetrics": {
                nombre: float(valor) for nombre, valor in disponibles.items()
            },
            "unavailable_metrics": [
                nombre for nombre, valor in partes.items() if valor is None
            ],
            "achievement": logro_confirmado,
            "achievement_name": NOMBRES_LOGRO[categoria] if logro_confirmado else None,
            "achievement_provisional": umbral_alcanzado and not logro_confirmado,
            "provisional_achievement_name": NOMBRES_LOGRO[categoria]
            if umbral_alcanzado and not logro_confirmado
            else None,
            "completeness": len(disponibles) / len(partes),
            "defensive_metrics": {
                "damage_taken": float(dano_recibido)
                if dano_recibido is not None
                else None,
                "damage_self_mitigated": float(dano_mitigado)
                if dano_mitigado is not None
                else None,
                "team_kills": float(kills_equipo) if kills_equipo is not None else None,
                "kill_participation": float(participacion)
                if participacion is not None
                else None,
                "useful_damage_taken": float(dano_util)
                if dano_util is not None
                else None,
                "useful_damage_taken_points": puntos_dano_util,
                "useful_mitigated_damage": float(dano_mitigado_util)
                if dano_mitigado_util is not None
                else None,
                "useful_mitigated_damage_points": puntos_dano_mitigado,
            }
            if categoria == "supervivencia"
            else None,
        }
    completitud = sum(v["completeness"] for v in categorias.values()) / len(categorias)
    return {
        "participant_id": entrada.id_participante,
        "champion": entrada.campeon,
        "team": entrada.equipo,
        "role": entrada.rol,
        "version": VERSION_PUNTUACION,
        "calibration_version": "2026.10",
        "metric_sources": FUENTES_METRICAS,
        "mode": modo,
        "multiplicador_duracion": float(multiplicador),
        "duration_seconds": duracion_segundos,
        "categories": categorias,
        "total": sum(v["final"] for v in categorias.values()),
        "completeness": completitud,
        "awards": [],
        "achievements_provisional": modo == "live",
    }


def clasificar_jugadores(
    entradas: list[EntradaRendimientoJugador],
    duracion_segundos: int,
    ganador: str | None = None,
    modo: str = "live",
) -> dict[str, Any]:
    """Clasifica entradas por duración, ganador y modo; devuelve rangos y premios."""
    resultados = [
        puntuar_jugador(entrada, duracion_segundos, modo) for entrada in entradas
    ]
    ordenados = sorted(
        resultados, key=lambda item: (-item["total"], item["participant_id"])
    )
    rango_anterior = 0
    puntuacion_anterior: int | None = None
    for indice, jugador in enumerate(ordenados, 1):
        if puntuacion_anterior != jugador["total"]:
            rango_anterior = indice
        jugador["global_rank"] = rango_anterior
        equipo = sorted(
            (p for p in ordenados if p["team"] == jugador["team"]),
            key=lambda p: (-p["total"], p["participant_id"]),
        )
        jugador["team_rank"] = 1 + sum(p["total"] > jugador["total"] for p in equipo)
        puntuacion_anterior = jugador["total"]
    datos_comparables = (
        len(ordenados) == 10
        and all(
            all(
                nombre in jugador["categories"]["combate"]["submetrics"]
                for nombre in (
                    "participacion",
                    "bajas_y_asistencias",
                    "eficiencia_combate",
                )
            )
            and jugador["completeness"] >= 0.25
            for jugador in ordenados
        )
        and len({jugador["team"] for jugador in ordenados}) == 2
    )
    premios_finales = (
        modo == "postgame" and bool(ganador) and bool(ordenados) and datos_comparables
    )
    for jugador in ordenados:
        jugador["awards_finalized"] = premios_finales
        jugador["faker_unlocked"] = jugador["total"] > 1000
        jugador["faker_provisional"] = jugador["faker_unlocked"] and not premios_finales
        jugador["finalization_state"] = (
            "POSTGAME_FINAL"
            if premios_finales
            else "LIVE_PROVISIONAL"
            if modo == "live"
            else "POSTGAME_PENDING"
        )
    if premios_finales:
        maximo = ordenados[0]["total"]
        for jugador in ordenados:
            if jugador["total"] == maximo:
                jugador["awards"].append(
                    "MVP/SVP" if jugador["team"] != ganador else "MVP"
                )
        perdedores = [p for p in ordenados if p["team"] != ganador]
        if perdedores:
            max_perdedor = perdedores[0]["total"]
            for jugador in perdedores:
                if (
                    jugador["total"] == max_perdedor
                    and "SVP" not in jugador["awards"]
                    and "MVP/SVP" not in jugador["awards"]
                ):
                    jugador["awards"].append("SVP")
    elif modo == "live":
        for jugador in ordenados:
            if jugador["global_rank"] == 1:
                jugador["awards"].append("Líder provisional")
    resumenes_equipo: dict[str, dict[str, Any]] = {}
    comparacion_equipos_valida = (
        len(ordenados) == 10 and len({j["team"] for j in ordenados}) == 2
    )
    for equipo in sorted({jugador["team"] for jugador in ordenados}):
        miembros = [jugador for jugador in ordenados if jugador["team"] == equipo]
        suficientes = len(miembros) == 5
        comparables = suficientes and all(
            jugador["version"] == VERSION_PUNTUACION
            and jugador["completeness"] >= 0.25
            and all(
                nombre in jugador["categories"]["combate"]["submetrics"]
                for nombre in (
                    "participacion",
                    "bajas_y_asistencias",
                    "eficiencia_combate",
                )
            )
            for jugador in miembros
        )
        comparacion_equipos_valida = comparacion_equipos_valida and comparables
        media_total = (
            sum(jugador["total"] for jugador in miembros) / 5 if suficientes else None
        )
        medias_categoria = (
            {
                categoria: sum(
                    jugador["categories"][categoria]["final"] for jugador in miembros
                )
                / 5
                for categoria in REFERENCIAS
            }
            if suficientes
            else {}
        )
        resumenes_equipo[equipo] = {
            "team": equipo,
            "player_count": len(miembros),
            "score": media_total,
            "categories": medias_categoria,
            "completeness": sum(jugador["completeness"] for jugador in miembros)
            / len(miembros)
            if miembros
            else 0,
            "comparable": comparables,
            "t1_unlocked": bool(
                comparables
                and media_total is not None
                and media_total > 1000
                and modo == "postgame"
            ),
            "t1_provisional": bool(
                comparables
                and media_total is not None
                and media_total > 1000
                and modo == "live"
            ),
            "result": "victoria"
            if equipo == ganador
            else "derrota"
            if ganador
            else None,
            "mode": modo,
            "version": VERSION_PUNTUACION,
        }
    for resumen in resumenes_equipo.values():
        puntuacion_equipo = resumen["score"]
        resumen["comparable"] = comparacion_equipos_valida
        resumen["t1_unlocked"] = bool(
            comparacion_equipos_valida
            and puntuacion_equipo is not None
            and puntuacion_equipo > 1000
            and modo == "postgame"
        )
        resumen["t1_provisional"] = bool(
            comparacion_equipos_valida
            and puntuacion_equipo is not None
            and puntuacion_equipo > 1000
            and modo == "live"
        )
    return {
        "players": ordenados,
        "by_id": {p["participant_id"]: p for p in ordenados},
        "version": VERSION_PUNTUACION,
        "calibration_version": "2026.10",
        "metric_sources": FUENTES_METRICAS,
        "mode": modo,
        "awards_finalized": premios_finales,
        "finalization_state": "POSTGAME_FINAL"
        if premios_finales
        else "LIVE_PROVISIONAL"
        if modo == "live"
        else "POSTGAME_PENDING",
        "pending_reason": None
        if premios_finales
        else "Faltan datos oficiales comparables o no se ha confirmado el equipo ganador."
        if modo == "postgame"
        else None,
        "multiplicador_duracion": float(multiplicador_duracion(duracion_segundos)),
        "teams": resumenes_equipo,
    }


def puntuar_sesion(sesion: dict[str, Any], modo: str = "live") -> dict[str, Any]:
    """Adapta sesión y modo al motor común; devuelve resultados por jugador."""
    jugadores = sesion.get("players", {})
    if not isinstance(jugadores, dict):
        return clasificar_jugadores([], int(sesion.get("duration", 0) or 0), modo=modo)
    puntos = {}
    for snapshot in sesion.get("snapshots", []):
        if not isinstance(snapshot, dict) or not isinstance(
            snapshot.get("players"), dict
        ):
            continue
        for clave, punto in snapshot["players"].items():
            if isinstance(punto, dict):
                puntos[clave] = punto
    final = sesion.get("final_scoreboard", {})
    entradas = []
    totales_bajas: dict[str, int] = {}
    equipos_bajas_incompletas: set[str] = set()
    totales_dano: dict[str, Decimal] = {}
    totales_oro: dict[str, Decimal] = {}
    conteo_equipo: dict[str, int] = {}
    for clave, jugador in jugadores.items():
        punto = dict(puntos.get(clave, {}))
        final_jugador = final.get(clave, {}) if isinstance(final, dict) else {}
        if isinstance(final_jugador, dict):
            punto.update(final_jugador)
        estadisticas = punto.get("stats", {})
        estadisticas = estadisticas if isinstance(estadisticas, dict) else {}
        equipo = str(jugador.get("team") or "")
        final_anidado = jugador.get("final", {})
        final_jugador = dict(final_anidado) if isinstance(final_anidado, dict) else {}
        final_jugador.update(punto)
        bajas = _numero(punto, "kills")
        if bajas is None:
            equipos_bajas_incompletas.add(equipo)
        else:
            totales_bajas[equipo] = totales_bajas.get(equipo, 0) + int(bajas)
        oro_ganado = final_jugador.get("gold_earned")
        if oro_ganado is not None:
            totales_oro[equipo] = totales_oro.get(equipo, Decimal(0)) + Decimal(
                str(oro_ganado or 0)
            )
            conteo_equipo[equipo] = conteo_equipo.get(equipo, 0) + 1
        dano = punto.get(
            "damage_champions", final_jugador.get("total_damage_dealt_to_champions")
        )
        if dano is not None:
            totales_dano[equipo] = totales_dano.get(equipo, Decimal(0)) + Decimal(
                str(dano or 0)
            )
        entradas.append((clave, jugador, punto, estadisticas, final_jugador, equipo))
    normalizadas = []
    for clave, jugador, punto, estadisticas, final_jugador, equipo in entradas:
        datos: dict[str, Any] = {
            "kills": punto.get("kills", final_jugador.get("kills")),
            "deaths": punto.get("deaths", final_jugador.get("deaths")),
            "assists": punto.get("assists", final_jugador.get("assists")),
            "cs": punto.get("cs", final_jugador.get("cs_total")),
            "earned_gold": final_jugador.get("gold_earned"),
            "gold": punto.get("estimated_gold"),
            "vision": estadisticas.get(
                "vision_score", final_jugador.get("vision_score")
            ),
            "damage_champions": estadisticas.get(
                "damage_champions", final_jugador.get("total_damage_dealt_to_champions")
            ),
            "team_damage_champions": totales_dano.get(equipo),
            "team_gold_average_per_minute": (
                totales_oro[equipo] / max(1, conteo_equipo[equipo])
            )
            / max(Decimal(1), Decimal(int(sesion.get("duration", 0) or 0)) / 60)
            if equipo in totales_oro and conteo_equipo.get(equipo)
            else None,
            "damage_structures": final_jugador.get(
                "damage_dealt_to_turrets",
                final_jugador.get("damage_dealt_to_buildings"),
            ),
            "structure_contributions": (final_jugador.get("turret_kills", 0) or 0)
            + (final_jugador.get("inhibitor_kills", 0) or 0)
            if "turret_kills" in final_jugador or "inhibitor_kills" in final_jugador
            else None,
            "objective_participation": min(
                1,
                (final_jugador.get("objectives_stolen", 0) or 0)
                + (final_jugador.get("objectives_stolen_assists", 0) or 0),
            )
            if "objectives_stolen" in final_jugador
            or "objectives_stolen_assists" in final_jugador
            else None,
            "map_pressure": min(
                1, (_numero(final_jugador, "damage_dealt_to_objectives") or 0) / 10000
            )
            if final_jugador.get("damage_dealt_to_objectives") is not None
            else None,
            "damage_taken": final_jugador.get("damage_taken")
            if final_jugador.get("damage_taken") is not None
            else estadisticas.get("damage_taken"),
            "damage_self_mitigated": final_jugador.get("damage_self_mitigated")
            if final_jugador.get("damage_self_mitigated") is not None
            else estadisticas.get("damage_self_mitigated"),
            "cc_time": estadisticas.get(
                "time_ccing_others", final_jugador.get("total_time_crowd_control_dealt")
            ),
            "wards_placed": estadisticas.get(
                "wards_placed", final_jugador.get("wards_placed")
            ),
            "wards_killed": estadisticas.get(
                "wards_killed", final_jugador.get("wards_killed")
            ),
            "healing_allies": final_jugador.get("total_heals_on_teammates"),
            "shielding_allies": final_jugador.get("total_damage_shielded_on_teammates"),
            "self_healing": (
                max(
                    0,
                    final_jugador["total_heal"]
                    - final_jugador["total_heals_on_teammates"],
                )
                if final_jugador.get("total_heal") is not None
                and final_jugador.get("total_heals_on_teammates") is not None
                else None
            ),
            "damage_objectives": final_jugador.get("damage_dealt_to_objectives"),
            "team_kills": (
                totales_bajas.get(equipo)
                if equipo not in equipos_bajas_incompletas
                else None
            ),
        }
        normalizadas.append(
            EntradaRendimientoJugador(
                str(clave),
                str(jugador.get("champion_name") or ""),
                equipo,
                str(jugador.get("role") or "UNKNOWN"),
                datos,
            )
        )
    equipos_conocidos = {
        str(jugador.get("team") or "")
        for jugador in jugadores.values()
        if isinstance(jugador, dict)
    }
    ganador = sesion.get("winning_team")
    if ganador not in equipos_conocidos:
        ganador = None
    if not ganador:
        victorias = {
            str(jugador.get("team") or ""): jugador.get(
                "win",
                (sesion.get("final_scoreboard", {}).get(clave, {}) or {}).get("win"),
            )
            for clave, jugador in jugadores.items()
            if isinstance(jugador, dict)
            and jugador.get(
                "win",
                (sesion.get("final_scoreboard", {}).get(clave, {}) or {}).get("win"),
            )
            is not None
        }
        equipos_ganadores = [
            equipo for equipo, victoria in victorias.items() if victoria is True
        ]
        if len(equipos_conocidos) == 2 and len(equipos_ganadores) == 1:
            ganador = equipos_ganadores[0]
    final_sync = sesion.get("final_sync")
    estado_final = bool(
        sesion.get("postgame")
        or (isinstance(final_sync, dict) and final_sync.get("status") == "synced")
    )
    modo_real = "postgame" if estado_final else modo
    clasificación = clasificar_jugadores(
        normalizadas,
        int(sesion.get("duration", 0) or 0),
        ganador,
        modo_real,
    )
    for clave, jugador in jugadores.items():
        resultado = clasificación["by_id"].get(str(clave))
        if resultado and isinstance(jugador, dict):
            resultado["riot_id"] = nombre_riot_visible(jugador)
    return clasificación
