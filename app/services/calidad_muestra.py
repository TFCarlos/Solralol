"""Estados y umbrales compartidos para interpretar muestras de estadísticas."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

UMBRAL_MUESTRA_NORMAL = 20


class EstadoMuestra(StrEnum):
    """Clasifica datos disponibles, parciales, ausentes o fallidos."""

    NORMAL_SAMPLE = "NORMAL_SAMPLE"
    LOW_SAMPLE = "LOW_SAMPLE"
    PARTIAL_DATA = "PARTIAL_DATA"
    NO_DATA = "NO_DATA"
    FETCH_ERROR = "FETCH_ERROR"


def clasificar_muestra(
    partidas: Any, secciones: bool, umbral: int = UMBRAL_MUESTRA_NORMAL
) -> EstadoMuestra:
    """Clasifica cobertura por partidas y contenido realmente disponible.

    Args:
        partidas: Tamaño de muestra entregado por la fuente para la selección.
        secciones: Indica si al menos una sección estadística válida está presente.
        umbral: Número de partidas a partir del cual la muestra se considera normal.

    Returns:
        Estado que distingue muestra baja, datos parciales y ausencia.
    """
    try:
        cantidad = int(partidas)
    except (TypeError, ValueError, OverflowError):
        cantidad = 0
    if cantidad <= 0:
        return EstadoMuestra.PARTIAL_DATA if secciones else EstadoMuestra.NO_DATA
    if not secciones:
        return EstadoMuestra.PARTIAL_DATA
    if cantidad < max(1, int(umbral)):
        return EstadoMuestra.LOW_SAMPLE
    return EstadoMuestra.NORMAL_SAMPLE
