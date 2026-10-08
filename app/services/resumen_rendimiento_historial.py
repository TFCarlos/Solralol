"""Adapta puntuaciones finales autoritativas para los historiales de partidas."""

from __future__ import annotations

from typing import Any

from app.services.servicio_puntuacion_rendimiento import (
    VERSION_PUNTUACION,
    puntuar_sesion,
)

VERSION_CALIBRACION = "2026.10"


def puntuacion_historial_vigente(resumen: Any) -> bool:
    """Valida que un resumen archivado pertenezca al modelo final vigente.

    Args:
        resumen: valor guardado en el historial ligero de Inicio.

    Returns:
        ``True`` si contiene una puntuación final de la versión actual.
    """
    if not isinstance(resumen, dict):
        return False
    try:
        puntos = int(resumen["points"])
        rango = int(resumen["global_rank"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    return bool(
        resumen.get("version") == VERSION_PUNTUACION
        and resumen.get("calibration_version") == VERSION_CALIBRACION
        and resumen.get("state") == "POSTGAME_FINAL"
        and puntos >= 0
        and rango >= 1
    )


def asegurar_puntuacion_guardada(sesion: dict[str, Any]) -> bool:
    """Calcula o actualiza el resultado versionado de una sesión postpartida.

    Args:
        sesion: registro mutable de una partida guardada.

    Returns:
        ``True`` si se creó o reemplazó el resultado persistible.
    """
    sincronizacion = sesion.get("final_sync")
    sincronizacion = sincronizacion if isinstance(sincronizacion, dict) else {}
    if sincronizacion.get("status") != "synced" and not sesion.get("postgame"):
        return False
    guardado = sesion.get("performance_scoring")
    guardado = guardado if isinstance(guardado, dict) else {}
    if (
        guardado.get("version") == VERSION_PUNTUACION
        and guardado.get("calibration_version") == VERSION_CALIBRACION
        and guardado.get("state") in {"POSTGAME_FINAL", "POSTGAME_PENDING"}
    ):
        return False
    try:
        ranking = puntuar_sesion(sesion, "postgame")
    except (ArithmeticError, KeyError, TypeError, ValueError):
        return False
    sesion["performance_scoring"] = {
        "version": ranking["version"],
        "calibration_version": ranking["calibration_version"],
        "metric_sources": ranking["metric_sources"],
        "state": ranking["finalization_state"],
        "awards_finalized": ranking["awards_finalized"],
        "duration_multiplier": ranking["multiplicador_duracion"],
        "players": ranking["players"],
        "teams": ranking["teams"],
    }
    return True


def resumen_puntuacion_local(sesion: dict[str, Any]) -> dict[str, Any] | None:
    """Devuelve el puesto final del participante local solo si es vigente.

    Args:
        sesion: partida con el resultado central persistido.

    Returns:
        Resumen local compacto, o ``None`` si no hay datos finales válidos.
    """
    sincronizacion = sesion.get("final_sync")
    sincronizacion = sincronizacion if isinstance(sincronizacion, dict) else {}
    guardado = sesion.get("performance_scoring")
    if not isinstance(guardado, dict) or (
        sincronizacion.get("status") != "synced"
        or guardado.get("version") != VERSION_PUNTUACION
        or guardado.get("calibration_version") != VERSION_CALIBRACION
        or guardado.get("state") != "POSTGAME_FINAL"
        or guardado.get("awards_finalized") is not True
    ):
        return None
    clave_local = str(sesion.get("local_player_key") or "")
    jugadores = guardado.get("players")
    if not clave_local or not isinstance(jugadores, list):
        return None
    jugador = next(
        (
            valor
            for valor in jugadores
            if isinstance(valor, dict)
            and str(valor.get("participant_id") or "") == clave_local
        ),
        None,
    )
    if jugador is None:
        return None
    try:
        puntos = int(jugador["total"])
        rango = int(jugador["global_rank"])
    except (KeyError, TypeError, ValueError):
        return None
    premios = jugador.get("awards")
    premio = (
        next(
            (
                str(valor)
                for valor in premios
                if isinstance(valor, str) and valor in {"MVP", "SVP", "MVP/SVP"}
            ),
            "",
        )
        if isinstance(premios, list)
        else ""
    )
    return {
        "participant_id": clave_local,
        "points": puntos,
        "global_rank": rango,
        "award": premio,
        "version": guardado["version"],
        "calibration_version": guardado["calibration_version"],
        "state": guardado["state"],
        "completeness": float(jugador.get("completeness") or 0),
    }


def etiqueta_puntuacion(resumen: dict[str, Any]) -> str:
    """Formatea puntos, rango y premio como insignia compacta en español.

    Args:
        resumen: resumen final validado del jugador local.

    Returns:
        Texto compacto con separador de millares español.
    """
    puntos = f"{int(resumen['points']):,}".replace(",", ".")
    premio = str(resumen.get("award") or "")
    sufijo_premio = f" · {premio}" if premio else ""
    return f"{puntos}p · {int(resumen['global_rank'])}º{sufijo_premio}"
