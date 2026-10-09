"""Estado persistente y política de reintentos de postpartida mediante LCU."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

RETRASOS_REINTENTO_LCU = (2, 5, 15, 30, 60)
REINTENTO_LCU_RECUPERACION = 300
logger = logging.getLogger(__name__)


def marcar_sincronizacion_lcu_pendiente(sesion: dict[str, Any]) -> None:
    """Persiste una tarea LCU pendiente sin reiniciar intentos.

    Args:
        sesion: registro de partida guardado que acaba de finalizar.

    Returns:
        ``None``; modifica el estado LCU de la sesión recibida.
    """
    estado = sesion.get("lcu_postgame_sync")
    estado = estado if isinstance(estado, dict) else {}
    if estado.get("state") == "synced":
        return
    sesion["lcu_postgame_sync"] = {
        "state": "pending",
        "attempts": contador_intentos_lcu(estado),
        "session_id": str(sesion.get("session_id") or ""),
    }


def marcar_sincronizacion_lcu_completa(sesion: dict[str, Any]) -> None:
    """Persiste la finalización de la conciliación LCU.

    Args:
        sesion: registro cuya partida ya aparece enlazada en Home.

    Returns:
        ``None``; modifica solo el estado auxiliar de sincronización LCU.
    """
    estado = sesion.get("lcu_postgame_sync")
    estado = estado if isinstance(estado, dict) else {}
    sesion["lcu_postgame_sync"] = {
        "state": "synced",
        "attempts": contador_intentos_lcu(estado),
        "session_id": str(sesion.get("session_id") or ""),
    }


def siguiente_retraso_lcu(intentos: int) -> int:
    """Selecciona un retraso de reintento sin sondeo intensivo.

    Args:
        intentos: número de intentos persistidos.

    Returns:
        Segundos hasta el siguiente intento o recuperación posterior.
    """
    indice = max(0, int(intentos))
    if indice < len(RETRASOS_REINTENTO_LCU):
        return RETRASOS_REINTENTO_LCU[indice]
    return REINTENTO_LCU_RECUPERACION


def historial_contiene_enlace(historial: dict[str, Any], session_id: str) -> bool:
    """Comprueba si Home ya asoció una partida con la sesión exacta.

    Args:
        historial: historial local ya fusionado.
        session_id: identificador estable de la sesión guardada.

    Returns:
        ``True`` si existe un enlace exacto confirmado.
    """
    partidas = historial.get("matches")
    if not isinstance(partidas, list):
        return False
    return any(
        isinstance(partida, dict)
        and isinstance(partida.get("saved_match_link"), dict)
        and partida["saved_match_link"].get("matched") is True
        and str(partida["saved_match_link"].get("saved_match_id") or "") == session_id
        for partida in partidas
    )


def incorporar_resultado_lcu(sesion: dict[str, Any], partida: dict[str, Any]) -> bool:
    """Incorpora datos LCU solo con roster e identidad verificables.

    Args:
        sesion: registro guardado con los diez participantes de LIVE.
        partida: resultado LCU normalizado y enlazado a esa sesión.

    Returns:
        ``True`` si actualizó la sesión; ``False`` si faltó evidencia fiable.
    """
    session_id = str(sesion.get("session_id") or "")
    enlace = partida.get("saved_match_link")
    if (
        not session_id
        or not isinstance(enlace, dict)
        or str(enlace.get("saved_match_id") or "") != session_id
    ):
        return False
    sincronizacion = sesion.get("final_sync")
    sincronizacion = sincronizacion if isinstance(sincronizacion, dict) else {}
    if sincronizacion.get("status") == "synced":
        return False
    jugadores = sesion.get("players")
    participantes = partida.get("participants")
    if (
        not isinstance(jugadores, dict)
        or not isinstance(participantes, list)
        or len(participantes) != 10
    ):
        return False
    indice: dict[tuple[str, str], str] = {}
    for clave, jugador in jugadores.items():
        if not isinstance(jugador, dict):
            continue
        identidades = {
            "puuid": jugador.get("puuid"),
            "account_id": jugador.get("account_id"),
            "summoner_id": jugador.get("summoner_id"),
            "participant_id": jugador.get("participant_id"),
        }
        riot_id = str(jugador.get("riot_id") or "").strip().casefold()
        for tipo, valor in identidades.items():
            if valor not in (None, ""):
                indice[(tipo, str(valor))] = str(clave)
        if riot_id:
            indice[("riot_id", riot_id)] = str(clave)
    mapeados: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for participante in participantes:
        if not isinstance(participante, dict):
            return False
        clave = next(
            (
                indice[(tipo, str(participante[campo]))]
                for tipo, campo in (
                    ("puuid", "puuid"),
                    ("account_id", "account_id"),
                    ("summoner_id", "summoner_id"),
                    ("participant_id", "participant_id"),
                )
                if participante.get(campo) not in (None, "")
                and (tipo, str(participante[campo])) in indice
            ),
            None,
        )
        riot_id = "#".join(
            str(participante.get(campo) or "").strip()
            for campo in ("game_name", "tag_line")
        ).casefold()
        if clave is None and riot_id in indice:
            clave = indice[("riot_id", riot_id)]
        estadisticas = participante.get("final_stats")
        if clave is None or clave in mapeados or not isinstance(estadisticas, dict):
            return False
        if any(
            estadisticas.get(campo) is None for campo in ("kills", "deaths", "assists")
        ):
            return False
        mapeados[clave] = (participante, estadisticas)
    if set(mapeados) != set(jugadores) or len(jugadores) != 10:
        return False
    equipos = {str(jugador.get("team") or "") for jugador in jugadores.values()}
    if len(equipos) != 2 or any(
        sum(str(jugadores[clave].get("team") or "") == equipo for clave in mapeados)
        != 5
        for equipo in equipos
    ):
        return False
    clave_local = str(sesion.get("local_player_key") or "")
    if clave_local not in mapeados:
        return False
    participante_local = mapeados[clave_local][0]
    jugador_local = jugadores[clave_local]
    for campo in ("puuid", "account_id", "summoner_id", "participant_id"):
        esperado = jugador_local.get(campo)
        observado = participante_local.get(campo)
        if (
            esperado not in (None, "")
            and observado not in (None, "")
            and str(esperado) != str(observado)
        ):
            return False
    resultado_por_equipo: dict[str, bool] = {}
    for clave, (participante, _) in mapeados.items():
        equipo = str(jugadores[clave].get("team") or "")
        victoria = participante.get("win")
        if not isinstance(victoria, bool):
            return False
        if equipo in resultado_por_equipo and resultado_por_equipo[equipo] != victoria:
            return False
        resultado_por_equipo[equipo] = victoria
    equipos_ganadores = [
        equipo for equipo, victoria in resultado_por_equipo.items() if victoria
    ]
    if len(equipos_ganadores) != 1:
        return False
    marcador: dict[str, dict[str, Any]] = {}
    for clave, (participante, estadisticas) in mapeados.items():
        meta = jugadores[clave]
        estadisticas_finales = dict(estadisticas)
        estadisticas_finales.update(
            {
                "kills": participante.get("kills"),
                "deaths": participante.get("deaths"),
                "assists": participante.get("assists"),
                "cs_total": participante.get("cs"),
                "gold_earned": estadisticas.get("gold_earned"),
                "total_damage_dealt_to_champions": estadisticas.get(
                    "total_damage_dealt_to_champions"
                ),
                "damage_dealt_to_turrets": estadisticas.get("damage_dealt_to_turrets"),
                "damage_dealt_to_objectives": estadisticas.get(
                    "damage_dealt_to_objectives"
                ),
                "vision_score": estadisticas.get("vision_score"),
                "total_time_crowd_control_dealt": estadisticas.get(
                    "total_time_crowd_control_dealt"
                ),
                "wards_placed": estadisticas.get("wards_placed"),
                "wards_killed": estadisticas.get("wards_killed"),
                "total_heal": estadisticas.get("total_heal"),
                "total_heals_on_teammates": estadisticas.get(
                    "total_heals_on_teammates"
                ),
                "total_damage_shielded_on_teammates": estadisticas.get(
                    "total_damage_shielded_on_teammates"
                ),
            }
        )
        meta["final"] = estadisticas_finales
        meta["win"] = participante.get("win")
        marcador[clave] = {
            "kills": participante.get("kills"),
            "deaths": participante.get("deaths"),
            "assists": participante.get("assists"),
            "cs": participante.get("cs"),
            "stats": {
                "vision_score": estadisticas.get("vision_score"),
                "damage_champions": estadisticas.get("total_damage_dealt_to_champions"),
                "damage_taken": estadisticas.get("damage_taken"),
                "damage_self_mitigated": estadisticas.get("damage_self_mitigated"),
                "time_ccing_others": estadisticas.get("total_time_crowd_control_dealt"),
                "wards_placed": estadisticas.get("wards_placed"),
                "wards_killed": estadisticas.get("wards_killed"),
            },
            "estimated_gold": estadisticas.get("gold_earned"),
            "items": participante.get("items", []),
        }
    sesion["duration"] = int(
        partida.get("duration_seconds") or sesion.get("duration") or 0
    )
    sesion["final_scoreboard"] = marcador
    sesion["winning_team"] = equipos_ganadores[0]
    sesion["postgame"] = True
    game_id = str(partida.get("game_id") or "")
    sesion["final_sync"] = {
        "status": "synced",
        "match_id": f"LCU_{game_id}" if game_id else "",
        "synced_at": datetime.now(UTC).isoformat(),
        "source": "lcu_match_history",
        "message": "Estadísticas finales obtenidas del League Client.",
    }
    sesion["lcu_postgame_sync"] = {
        "state": "synced",
        "attempts": contador_intentos_lcu(sesion.get("lcu_postgame_sync")),
        "session_id": session_id,
    }
    return True


def reconciliar_puntuaciones_home(
    partidas: list[dict[str, Any]],
    sesiones: list[dict[str, Any]],
    puuid_cuenta: str | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Vincula sesiones exactas y genera Home con el motor BattleScore central.

    Args:
        partidas: historial LCU normalizado.
        sesiones: sesiones guardadas mutables para persistir enriquecimientos.
        puuid_cuenta: identidad local de la cuenta activa, si está disponible.

    Returns:
        Historial enlazado y si alguna sesión necesita persistirse.
    """
    from app.services.home_history_service import (
        _coincide_cuenta_local,
        cross_reference_saved_matches,
    )
    from app.services.resumen_rendimiento_historial import asegurar_puntuacion_guardada

    vinculadas = cross_reference_saved_matches(partidas, sesiones, puuid_cuenta)
    sesiones_por_id = {
        str(sesion.get("session_id") or ""): sesion
        for sesion in sesiones
        if isinstance(sesion, dict) and sesion.get("session_id")
    }
    actualizadas = False
    detalles_lcu = 0
    for partida in vinculadas:
        enlace = partida.get("saved_match_link")
        session_id = (
            str(enlace.get("saved_match_id") or "") if isinstance(enlace, dict) else ""
        )
        sesion = sesiones_por_id.get(session_id)
        enlace = partida.get("saved_match_link")
        asociacion_confirmada = bool(
            isinstance(enlace, dict) and enlace.get("association") == "exact"
        )
        if sesion is not None and _coincide_cuenta_local(
            partida,
            sesion,
            puuid_cuenta,
            asociacion_confirmada=asociacion_confirmada,
        ):
            incorporada = incorporar_resultado_lcu(sesion, partida)
            actualizadas |= incorporada
            detalles_lcu += int(incorporada)
    for sesion in sesiones:
        if isinstance(sesion, dict):
            actualizadas |= asegurar_puntuacion_guardada(sesion)
    resultado = cross_reference_saved_matches(vinculadas, sesiones, puuid_cuenta)
    resúmenes = sum(
        isinstance(partida.get("performance_summary"), dict) for partida in resultado
    )
    logger.info(
        "[home-battlescore] analizables=%s vinculadas=%s detalle_lcu=%s resumen_final=%s",
        sum(partida.get("analyzable") is True for partida in resultado),
        sum(
            bool(
                sesiones_por_id.get(
                    str(
                        (partida.get("saved_match_link") or {}).get("saved_match_id")
                        or ""
                    )
                )
            )
            for partida in resultado
        ),
        detalles_lcu,
        resúmenes,
    )
    return resultado, actualizadas


def conservar_enriquecimiento_final(
    actual: dict[str, Any], entrante: dict[str, Any]
) -> dict[str, Any]:
    """Evita que una actualización antigua reemplace datos finales ya guardados.

    Args:
        actual: versión más reciente que ya está persistida.
        entrante: copia producida por una sincronización que acaba de finalizar.

    Returns:
        Copia entrante con resultados finales actuales preservados cuando faltan.
    """
    resultado = deepcopy(entrante)
    actual_sync = actual.get("final_sync")
    actual_sync = actual_sync if isinstance(actual_sync, dict) else {}
    entrante_sync = resultado.get("final_sync")
    entrante_sync = entrante_sync if isinstance(entrante_sync, dict) else {}
    if (
        actual_sync.get("status") == "synced"
        and entrante_sync.get("status") != "synced"
    ):
        for campo in (
            "final_sync",
            "final_scoreboard",
            "winning_team",
            "postgame",
            "riot_match",
            "riot_timeline",
            "official_events",
            "events",
        ):
            if campo in actual:
                resultado[campo] = deepcopy(actual[campo])
    puntuacion_actual = actual.get("performance_scoring")
    puntuacion_actual = puntuacion_actual if isinstance(puntuacion_actual, dict) else {}
    puntuacion_entrante = resultado.get("performance_scoring")
    puntuacion_entrante = (
        puntuacion_entrante if isinstance(puntuacion_entrante, dict) else {}
    )
    if (
        puntuacion_actual.get("state") == "POSTGAME_FINAL"
        and puntuacion_entrante.get("state") != "POSTGAME_FINAL"
    ):
        resultado["performance_scoring"] = deepcopy(puntuacion_actual)
    sync_lcu_actual = actual.get("lcu_postgame_sync")
    sync_lcu_actual = sync_lcu_actual if isinstance(sync_lcu_actual, dict) else {}
    sync_lcu_entrante = resultado.get("lcu_postgame_sync")
    sync_lcu_entrante = sync_lcu_entrante if isinstance(sync_lcu_entrante, dict) else {}
    if (
        sync_lcu_actual.get("state") == "synced"
        and sync_lcu_entrante.get("state") != "synced"
    ):
        resultado["lcu_postgame_sync"] = deepcopy(sync_lcu_actual)
    return resultado


def actualizar_estado_sync_final(
    sesion: dict[str, Any], estado_nuevo: str, mensaje: str
) -> bool:
    """Actualiza el estado remoto sin degradar una sincronización final válida.

    Args:
        sesion: partida guardada que conserva su estado final actual.
        estado_nuevo: estado del intento de sincronización más reciente.
        mensaje: detalle breve de dicho intento.

    Returns:
        ``True`` si aplicó el estado; ``False`` si protegió un resultado final.
    """
    estado_actual = sesion.get("final_sync")
    estado_actual = estado_actual if isinstance(estado_actual, dict) else {}
    if estado_actual.get("status") == "synced" and estado_nuevo != "synced":
        return False
    estado_actual["status"] = estado_nuevo
    estado_actual["message"] = mensaje
    sesion["final_sync"] = estado_actual
    return True


def contador_intentos_lcu(estado: Any) -> int:
    """Lee el contador de intentos de un estado posiblemente antiguo.

    Args:
        estado: estado de sincronización persistido.

    Returns:
        Contador entero no negativo, con cero como valor seguro.
    """
    if not isinstance(estado, dict):
        return 0
    try:
        return max(0, int(estado.get("attempts") or 0))
    except (TypeError, ValueError, OverflowError):
        return 0
