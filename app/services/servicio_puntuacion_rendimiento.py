"""Compatibility facade for the authoritative BattleScore 2.0 engine.

Live Client snapshots and legacy session summaries do not contain the verified
Riot chronology required to calculate an official BattleScore. They therefore
remain unavailable here; the Electron Riot analysis pipeline owns scoring.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from backend.battlescore import VERSION as VERSION_PUNTUACION

VERSION_CALIBRACION = VERSION_PUNTUACION

# Retained as a compatibility contract for current analytics consumers. These
# labels do not correspond to independent weighted scoring formulas.
REFERENCIAS = {"combate": 10, "economia": 10, "objetivos": 10, "vision": 10, "supervivencia": 10}
TITULOS_CATEGORIA = {
    "combate": "Combate", "economia": "Economía", "objetivos": "Objetivos",
    "vision": "Visión", "supervivencia": "Supervivencia",
}
NOMBRES_METRICAS: dict[str, str] = {}
FUENTES_METRICAS: dict[str, str] = {}


@dataclass(frozen=True)
class EntradaRendimientoJugador:
    id_participante: str
    campeon: str
    equipo: str
    rol: str
    estadisticas: dict[str, Any]


def puntuar_jugador(entrada: EntradaRendimientoJugador, duracion_segundos: int, modo: str = "live") -> dict[str, Any]:
    """Return an unavailable result; aggregate snapshot inputs cannot be scored."""
    return {
        "participant_id": entrada.id_participante, "champion": entrada.campeon,
        "team": entrada.equipo, "role": entrada.rol, "version": VERSION_PUNTUACION,
        "calibration_version": VERSION_CALIBRACION, "state": "UNAVAILABLE",
        "total": None, "series": [], "categories": {}, "completeness": 0.0,
        "awards": [], "unavailable_reason": "Falta cronología Riot verificable.",
    }


def clasificar_jugadores(entradas: list[EntradaRendimientoJugador], duracion_segundos: int,
                         ganador: str | None = None, modo: str = "live") -> dict[str, Any]:
    """Do not infer scores or rankings from final or current aggregate stats."""
    return {
        "players": [], "by_id": {}, "teams": {}, "version": VERSION_PUNTUACION,
        "calibration_version": VERSION_CALIBRACION, "mode": modo,
        "metric_sources": {},
        "awards_finalized": False, "finalization_state": "UNAVAILABLE",
        "pending_reason": "BattleScore necesita cronología Riot verificada.",
        "multiplicador_duracion": 1.0,
    }


def puntuar_sesion(sesion: dict[str, Any], modo: str = "live") -> dict[str, Any]:
    """Legacy session snapshots are not an authoritative BattleScore source."""
    return clasificar_jugadores([], int(sesion.get("duration", 0) or 0), modo=modo)
